import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from nutrition import FoodDatabase, UserProfile, WeeklyMenuGenerator


def collect_food_names(menu):
    return {
        item.food.name
        for day in menu.days
        for meal in day.meals
        for item in meal.items
    }


def collect_daily_calories(menu):
    return [day.totals["calories"] for day in menu.days]


def collect_tag_usage(menu, tag):
    usages = []
    for day in menu.days:
        for meal in day.meals:
            for item in meal.items:
                usages.append(tag in item.food.tags)
    return usages


class WeeklyMenuGeneratorTests(unittest.TestCase):
    def setUp(self):
        table_path = os.path.join(PROJECT_ROOT, "resources", "tabla_equivalencias.csv")
        self.database = FoodDatabase(Path(table_path))
        self.generator = WeeklyMenuGenerator(self.database)

    def test_included_foods_are_present(self):
        profile = UserProfile(
            height_cm=170,
            weight_kg=65,
            age=28,
            goal="Ganancia muscular",
            daily_calories=2500,
            include_foods=[
                "Arroz integral cocido",
                "Pechuga de pollo",
                "Hummus",
                "Pasta de lentejas cocida",
            ],
            restrictions=["sin gluten"],
        )
        menu = self.generator.generate_weekly_menu(profile)
        names = collect_food_names(menu)
        for expected in profile.include_foods:
            self.assertIn(expected, names)

    def test_daily_calories_do_not_exceed_target(self):
        profile = UserProfile(
            height_cm=180,
            weight_kg=80,
            age=32,
            goal="Pérdida de grasa",
            daily_calories=2000,
            restrictions=["sin gluten"],
        )
        menu = self.generator.generate_weekly_menu(profile)
        daily_totals = collect_daily_calories(menu)
        for total in daily_totals:
            self.assertLessEqual(total, profile.daily_calories + 5)

    def test_restriction_excludes_tagged_foods(self):
        profile = UserProfile(
            height_cm=165,
            weight_kg=60,
            age=26,
            goal="Mantenimiento",
            daily_calories=1900,
            restrictions=["sin gluten"],
        )
        menu = self.generator.generate_weekly_menu(profile)
        for day in menu.days:
            for meal in day.meals:
                for item in meal.items:
                    self.assertNotIn("gluten", item.food.tags)


if __name__ == "__main__":
    unittest.main()
