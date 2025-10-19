"""Weekly nutrition planner utilities.

This module loads food nutritional equivalences and generates weekly menus that
respect user calorie targets, preferred foods, and dietary restrictions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import cycle
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple
import csv


@dataclass(frozen=True)
class Food:
    """Represents the nutritional information of a food item per 100 grams."""

    name: str
    calories: float
    protein: float
    carbs: float
    fat: float
    tags: Set[str] = field(default_factory=set)

    @property
    def calories_per_gram(self) -> float:
        return self.calories / 100.0

    def to_macros(self, grams: float) -> Tuple[float, float, float, float]:
        factor = grams / 100.0
        return (
            round(self.calories * factor, 2),
            round(self.protein * factor, 2),
            round(self.carbs * factor, 2),
            round(self.fat * factor, 2),
        )


@dataclass
class MealItem:
    food: Food
    grams: float

    @property
    def macros(self) -> Dict[str, float]:
        calories, protein, carbs, fat = self.food.to_macros(self.grams)
        return {
            "calories": calories,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
        }


@dataclass
class MealPlan:
    name: str
    items: List[MealItem]

    @property
    def totals(self) -> Dict[str, float]:
        totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
        for item in self.items:
            macros = item.macros
            totals["calories"] += macros["calories"]
            totals["protein"] += macros["protein"]
            totals["carbs"] += macros["carbs"]
            totals["fat"] += macros["fat"]
        for key in totals:
            totals[key] = round(totals[key], 2)
        return totals


@dataclass
class DayPlan:
    day: int
    meals: List[MealPlan]

    @property
    def totals(self) -> Dict[str, float]:
        totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
        for meal in self.meals:
            meal_totals = meal.totals
            for key, value in meal_totals.items():
                totals[key] += value
        for key in totals:
            totals[key] = round(totals[key], 2)
        return totals


@dataclass
class WeeklyMenu:
    days: List[DayPlan]

    @property
    def shopping_list(self) -> Dict[str, float]:
        aggregated: Dict[str, float] = {}
        for day in self.days:
            for meal in day.meals:
                for item in meal.items:
                    aggregated[item.food.name] = aggregated.get(item.food.name, 0.0) + item.grams
        return {name: round(amount, 2) for name, amount in sorted(aggregated.items())}


@dataclass
class UserProfile:
    height_cm: int
    weight_kg: float
    age: int
    goal: str
    daily_calories: int
    include_foods: Sequence[str] = field(default_factory=list)
    avoid_foods: Sequence[str] = field(default_factory=list)
    restrictions: Sequence[str] = field(default_factory=list)


class FoodDatabase:
    """Loads the food equivalence table used by the planner."""

    def __init__(self, table_path: Path) -> None:
        if not table_path.exists():
            raise FileNotFoundError(f"Food table not found: {table_path}")
        self._foods = self._load(table_path)

    @staticmethod
    def _load(table_path: Path) -> Dict[str, Food]:
        foods: Dict[str, Food] = {}
        with table_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"name", "calories", "protein", "carbs", "fat", "tags"}
            if not required.issubset(reader.fieldnames or {}):
                missing = required - set(reader.fieldnames or set())
                raise ValueError(f"Missing columns in food table: {', '.join(sorted(missing))}")
            for row in reader:
                name = row["name"].strip()
                if not name:
                    continue
                tags = {tag.strip().lower() for tag in row["tags"].split(";") if tag.strip()}
                foods[name.lower()] = Food(
                    name=name,
                    calories=float(row["calories"]),
                    protein=float(row["protein"]),
                    carbs=float(row["carbs"]),
                    fat=float(row["fat"]),
                    tags=tags,
                )
        if not foods:
            raise ValueError("Food table is empty")
        return foods

    def get(self, name: str) -> Food:
        food = self._foods.get(name.lower())
        if food is None:
            raise KeyError(f"Food '{name}' not found in database")
        return food

    def values(self) -> Iterable[Food]:
        return self._foods.values()

    def filter(self, predicate) -> List[Food]:
        return [food for food in self.values() if predicate(food)]


class WeeklyMenuGenerator:
    """Generates weekly menus based on user information and preferences."""

    MEAL_ORDER = ["Desayuno", "Snack", "Comida", "Cena"]
    MEAL_RATIOS = {
        "Desayuno": 0.3,
        "Snack": 0.1,
        "Comida": 0.35,
        "Cena": 0.25,
    }

    def __init__(self, food_database: FoodDatabase) -> None:
        self.food_database = food_database

    def generate_weekly_menu(self, profile: UserProfile) -> WeeklyMenu:
        foods = self._filter_foods(profile)
        if not foods:
            raise ValueError("No foods available after applying restrictions")

        include_assignments = self._assign_included_foods(profile.include_foods, foods)
        protein_cycle, carb_cycle, fat_cycle, produce_cycle = self._build_category_cycles(foods)
        macro_targets = self._macro_distribution(profile.goal)

        days: List[DayPlan] = []
        for day_index in range(7):
            meals: List[MealPlan] = []
            calories_remaining = float(profile.daily_calories)
            for meal_index, meal_name in enumerate(self.MEAL_ORDER):
                included_items = include_assignments.get((day_index, meal_name), [])
                is_last_meal = meal_index == len(self.MEAL_ORDER) - 1
                target_calories = calories_remaining if is_last_meal else profile.daily_calories * self.MEAL_RATIOS[meal_name]
                meal_plan, consumed = self._plan_meal(
                    meal_name,
                    target_calories,
                    calories_remaining,
                    included_items,
                    macro_targets,
                    protein_cycle,
                    carb_cycle,
                    fat_cycle,
                    produce_cycle,
                )
                calories_remaining = max(0.0, round(calories_remaining - consumed, 2))
                meals.append(meal_plan)
            days.append(DayPlan(day=day_index + 1, meals=meals))
        return WeeklyMenu(days=days)

    def _filter_foods(self, profile: UserProfile) -> List[Food]:
        restrictions = {r.lower() for r in profile.restrictions}
        avoid = {a.lower() for a in profile.avoid_foods}

        def passes_restrictions(food: Food) -> bool:
            if food.name.lower() in avoid:
                return False
            if "sin gluten" in restrictions and "gluten" in food.tags:
                return False
            if "sin lactosa" in restrictions and "lactose" in food.tags:
                return False
            if "vegetariano" in restrictions and not ({"vegetarian", "vegan"} & food.tags):
                return False
            if "vegano" in restrictions and "vegan" not in food.tags:
                return False
            if "sin frutos secos" in restrictions and {"nuts"} & food.tags:
                return False
            return True

        return [food for food in self.food_database.values() if passes_restrictions(food)]

    def _assign_included_foods(self, include_foods: Sequence[str], foods: Sequence[Food]) -> Dict[Tuple[int, str], List[Food]]:
        assignments: Dict[Tuple[int, str], List[Food]] = {}
        available_by_name = {food.name.lower(): food for food in foods}
        slots = [
            (day_index, meal_name)
            for day_index in range(7)
            for meal_name in self.MEAL_ORDER
        ]
        slot_cycle = cycle(slots)
        for food_name in include_foods:
            key = next(slot_cycle)
            food = available_by_name.get(food_name.lower())
            if food is None:
                raise KeyError(f"Requested food '{food_name}' is not available after restrictions")
            assignments.setdefault(key, []).append(food)
        return assignments

    def _build_category_cycles(self, foods: Sequence[Food]):
        proteins = [food for food in foods if "protein" in food.tags]
        carbs = [food for food in foods if "carb" in food.tags]
        fats = [food for food in foods if "fat" in food.tags]
        produce = [food for food in foods if {"vegetable", "fruit"} & food.tags]

        def ensure(items: List[Food], fallback: List[Food]) -> List[Food]:
            return items if items else list(fallback)

        proteins = ensure(proteins, list(foods))
        carbs = ensure(carbs, list(foods))
        fats = ensure(fats, list(foods))
        produce = ensure(produce, list(foods))

        return (
            cycle(sorted(proteins, key=lambda f: f.name)),
            cycle(sorted(carbs, key=lambda f: f.name)),
            cycle(sorted(fats, key=lambda f: f.name)),
            cycle(sorted(produce, key=lambda f: f.name)),
        )

    def _plan_meal(
        self,
        meal_name: str,
        desired_calories: float,
        calories_remaining: float,
        included_foods: Sequence[Food],
        macro_targets: Dict[str, float],
        protein_cycle,
        carb_cycle,
        fat_cycle,
        produce_cycle,
    ) -> Tuple[MealPlan, float]:
        meal_foods: List[Food] = list(included_foods)
        desired_calories = max(120.0, min(desired_calories, calories_remaining))

        def add_food_from_cycle(food_cycle) -> None:
            next_food = next(food_cycle)
            if next_food not in meal_foods:
                meal_foods.append(next_food)

        if not any("protein" in food.tags for food in meal_foods):
            add_food_from_cycle(protein_cycle)
        if meal_name != "Snack" and not any("carb" in food.tags for food in meal_foods):
            add_food_from_cycle(carb_cycle)
        if not any({"vegetable", "fruit"} & food.tags for food in meal_foods):
            add_food_from_cycle(produce_cycle)
        if not any("fat" in food.tags for food in meal_foods):
            add_food_from_cycle(fat_cycle)

        target_count = 2 if meal_name == "Snack" else 3
        cycles = [protein_cycle, carb_cycle, fat_cycle, produce_cycle]
        cycle_index = 0
        while len(meal_foods) < target_count:
            add_food_from_cycle(cycles[cycle_index % len(cycles)])
            cycle_index += 1

        portions = self._allocate_portions(meal_foods, desired_calories, macro_targets)
        items = [MealItem(food=food, grams=grams) for food, grams in portions]
        total_calories = sum(item.macros["calories"] for item in items)
        return MealPlan(name=meal_name, items=items), round(total_calories, 2)

    def _allocate_portions(
        self,
        foods: Sequence[Food],
        target_calories: float,
        macro_targets: Dict[str, float],
    ) -> List[Tuple[Food, float]]:
        weights: List[float] = []
        for food in foods:
            if "protein" in food.tags:
                weights.append(macro_targets["protein"])
            elif "carb" in food.tags:
                weights.append(macro_targets["carbs"])
            elif "fat" in food.tags:
                weights.append(macro_targets["fat"])
            else:
                weights.append(1.0)
        weight_sum = sum(weights)
        if weight_sum == 0:
            weights = [1.0 for _ in foods]
            weight_sum = float(len(foods))
        normalized = [weight / weight_sum for weight in weights]

        portions: List[Tuple[Food, float]] = []
        for food, share in zip(foods, normalized):
            calories_share = max(40.0, target_calories * share)
            grams = calories_share / max(food.calories_per_gram, 1e-6)
            grams = self._bounded_grams(food, grams)
            portions.append((food, grams))

        total_calories = sum(food.to_macros(grams)[0] for food, grams in portions)
        if total_calories > 0:
            scale = min(1.0, target_calories / total_calories)
            if scale < 0.98:
                portions = [(food, self._round_grams(grams * scale)) for food, grams in portions]
                total_calories = sum(food.to_macros(grams)[0] for food, grams in portions)
        if total_calories < target_calories * 0.85:
            scale = min(1.2, target_calories / max(total_calories, 1e-6))
            portions = [(food, self._round_grams(grams * scale)) for food, grams in portions]

        return [(food, self._round_grams(grams)) for food, grams in portions]

    @staticmethod
    def _bounded_grams(food: Food, grams: float) -> float:
        if "fat" in food.tags:
            grams = max(10.0, min(grams, 35.0))
        elif "protein" in food.tags:
            grams = max(60.0, min(grams, 220.0))
        elif "carb" in food.tags:
            grams = max(60.0, min(grams, 220.0))
        else:
            grams = max(40.0, min(grams, 200.0))
        return grams

    @staticmethod
    def _round_grams(grams: float) -> float:
        return round(grams / 5.0) * 5.0

    @staticmethod
    def _macro_distribution(goal: str) -> Dict[str, float]:
        goal_lower = goal.lower()
        if "ganancia" in goal_lower:
            return {"protein": 0.35, "carbs": 0.4, "fat": 0.25}
        if "pérdida" in goal_lower or "perdida" in goal_lower:
            return {"protein": 0.35, "carbs": 0.35, "fat": 0.3}
        return {"protein": 0.3, "carbs": 0.45, "fat": 0.25}
