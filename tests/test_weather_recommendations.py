import unittest
from server_test_support import load_test_server


server = load_test_server("_smart_daily_assistant_server_for_weather_tests")


class BuildWeatherRecommendationsTests(unittest.TestCase):
    city = "Bengaluru"

    def recommendations(self, **overrides):
        weather = {
            "success": True,
            "temperature_c": 20,
            "feels_like_c": 20,
            "precipitation_mm": 0,
            "wind_speed_kmh": 10,
            "weather_code": 0,
        }
        weather.update(overrides)
        return server.build_weather_recommendations(weather, self.city)

    def test_rain_and_thunderstorm_conditions(self):
        for weather_code in (61, 95):
            with self.subTest(weather_code=weather_code):
                result = self.recommendations(weather_code=weather_code)
                self.assertEqual(result[0]["type"], "rain_or_storm")
                self.assertEqual(result[0]["action"], "prepare_for_rain")

    def test_extreme_heat_uses_feels_like_temperature(self):
        result = self.recommendations(
            temperature_c=25,
            feels_like_c=40,
        )
        self.assertIn("extreme_heat", [item["type"] for item in result])

    def test_strong_winds(self):
        result = self.recommendations(wind_speed_kmh=40)
        self.assertIn("strong_wind", [item["type"] for item in result])

    def test_benign_weather_returns_fallback(self):
        result = self.recommendations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "weather")
        self.assertEqual(result[0]["action"], "continue_as_planned")

    def test_weather_lookup_failure(self):
        result = server.build_weather_recommendations(
            {"success": False, "error": "service unavailable"},
            self.city,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "weather_unavailable")

    def test_missing_or_invalid_numeric_measurements_are_ignored(self):
        cases = {
            "missing measurements": {
                "success": True,
                "weather_code": 0,
            },
            "invalid measurement types": {
                "success": True,
                "temperature_c": "hot",
                "feels_like_c": True,
                "precipitation_mm": "unknown",
                "wind_speed_kmh": False,
                "weather_code": 0,
            },
        }

        for case_name, weather in cases.items():
            with self.subTest(case=case_name):
                result = server.build_weather_recommendations(
                    weather,
                    self.city,
                )
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["type"], "weather")

    def test_non_finite_measurements_are_ignored(self):
        cases = {
            "infinite feels-like temperature": {
                "feels_like_c": float("inf"),
            },
            "negative infinite temperature": {
                "temperature_c": float("-inf"),
                "feels_like_c": None,
            },
            "NaN precipitation": {
                "precipitation_mm": float("nan"),
            },
            "infinite wind speed": {
                "wind_speed_kmh": float("inf"),
            },
        }

        for case_name, overrides in cases.items():
            with self.subTest(case=case_name):
                result = self.recommendations(**overrides)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["type"], "weather")


if __name__ == "__main__":
    unittest.main()