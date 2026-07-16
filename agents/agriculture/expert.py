"""
Agriculture Expert Agent
========================
Tracks and forecasts state-level agricultural production for all 50 U.S.
states via USDA NASS (National Agricultural Statistics Service)
"Statistics by State" reporting.

Dashboard directory: https://www.nass.usda.gov/Statistics_by_State/index.php
API: https://quickstats.nass.usda.gov/api (free key; optional)
No API key required for calibrated proxy fallback; a Quick Stats API key
enables live commodity survey pulls.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

QUICKSTATS_API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
HEADERS = {"User-Agent": "Finance-Agriculture-Expert/1.0 (shaggychunxx@gmail.com)"}
NASS_STATE_DIRECTORY_URL = "https://www.nass.usda.gov/Statistics_by_State/index.php"

# Quick Stats commodity_desc values for internal commodity keys.
NASS_COMMODITY_QUERY: dict[str, str] = {
    "poultry_broilers": "BROILERS",
    "cotton": "COTTON",
    "all_hay_production": "HAY",
    "rice": "RICE",
    "cattle_and_calves": "CATTLE",
    "corn": "CORN",
    "soybeans": "SOYBEANS",
    "wheat": "WHEAT",
    "milk": "MILK",
    "hogs": "HOGS",
    "potatoes": "POTATOES",
    "oranges": "ORANGES",
    "grapes": "GRAPES",
    "almonds": "ALMONDS",
    "lettuce": "LETTUCE",
}

# Calibrated proxy history (illustrative, approximate NASS-reported magnitudes)
# used when quickstats.nass.usda.gov is unreachable or no API key is configured.
STATES: dict[str, dict[str, Any]] = {
    "alabama": {
        "name": "Alabama",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Alabama/index.php",
        "commodities": {
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 4200, 2020: 4121.0, 2021: 4292.0, 2022: 4365.0, 2023: 4449.0, 2024: 4334.0},
            },
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 480, 2020: 451.0, 2021: 458.0, 2022: 439.0, 2023: 440.0, 2024: 423.0},
            },
        },
    },
    "alaska": {
        "name": "Alaska",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Alaska/index.php",
        "commodities": {
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 45, 2020: 46.0, 2021: 45.0, 2022: 44.0, 2023: 44.0, 2024: 45.0},
            },
        },
    },
    "arizona": {
        "name": "Arizona",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Arizona/index.php",
        "commodities": {
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 130, 2020: 131.0, 2021: 133.0, 2022: 133.0, 2023: 131.0, 2024: 135.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 850, 2020: 867.0, 2021: 886.0, 2022: 855.0, 2023: 861.0, 2024: 883.0},
            },
        },
    },
    "arkansas": {
        "name": "Arkansas",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Arkansas/index.php",
        "commodities": {
            "rice": {
                "unit": "million cwt",
                "history": {2019: 95, 2020: 93.7, 2021: 92.7, 2022: 92.2, 2023: 92.5, 2024: 96.7},
            },
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 6900, 2020: 7187.0, 2021: 7082.0, 2022: 7445.0, 2023: 7316.0, 2024: 7590.0},
            },
        },
    },
    "california": {
        "name": "California",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/California/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 41000, 2020: 41967.0, 2021: 42426.0, 2022: 41242.0, 2023: 40136.0, 2024: 40369.0},
            },
            "almonds": {
                "unit": "million lbs",
                "history": {2019: 2260, 2020: 2442.0, 2021: 2479.0, 2022: 2602.0, 2023: 2723.0, 2024: 2932.0},
            },
        },
    },
    "colorado": {
        "name": "Colorado",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Colorado/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 85, 2020: 86.0, 2021: 83.0, 2022: 82.0, 2023: 79.0, 2024: 76.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 2650, 2020: 2589.0, 2021: 2659.0, 2022: 2583.0, 2023: 2491.0, 2024: 2545.0},
            },
        },
    },
    "connecticut": {
        "name": "Connecticut",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Connecticut/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 400, 2020: 381.0, 2021: 387.0, 2022: 394.0, 2023: 395.0, 2024: 376.0},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 60, 2020: 60.0, 2021: 61.0, 2022: 60.0, 2023: 59.0, 2024: 57.0},
            },
        },
    },
    "delaware": {
        "name": "Delaware",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Delaware/index.php",
        "commodities": {
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 2400, 2020: 2428.0, 2021: 2382.0, 2022: 2453.0, 2023: 2542.0, 2024: 2599.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 18, 2020: 18.0, 2021: 19.0, 2022: 19.0, 2023: 19.0, 2024: 19.0},
            },
        },
    },
    "florida": {
        "name": "Florida",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Florida/index.php",
        "commodities": {
            "citrus_oranges": {
                "unit": "million boxes",
                "history": {2019: 45, 2020: 39.0, 2021: 33.8, 2022: 30.3, 2023: 27.3, 2024: 24.9},
            },
            "sugarcane": {
                "unit": "million tons",
                "history": {2019: 16, 2020: 16.5, 2021: 16.3, 2022: 16.9, 2023: 16.5, 2024: 16.6},
            },
        },
    },
    "georgia": {
        "name": "Georgia",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Georgia/index.php",
        "commodities": {
            "peanuts": {
                "unit": "million lbs",
                "history": {2019: 3100, 2020: 3204.0, 2021: 3301.0, 2022: 3447.0, 2023: 3521.0, 2024: 3541.0},
            },
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 15500, 2020: 15781.0, 2021: 15542.0, 2022: 16116.0, 2023: 16506.0, 2024: 17215.0},
            },
        },
    },
    "hawaii": {
        "name": "Hawaii",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Hawaii/index.php",
        "commodities": {
            "coffee": {
                "unit": "thousand lbs",
                "history": {2019: 6600, 2020: 6656.0, 2021: 6653.0, 2022: 6611.0, 2023: 6624.0, 2024: 6724.0},
            },
            "macadamia_nuts": {
                "unit": "million lbs",
                "history": {2019: 40, 2020: 40.0, 2021: 39.4, 2022: 37.5, 2023: 37.7, 2024: 37.3},
            },
        },
    },
    "idaho": {
        "name": "Idaho",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Idaho/index.php",
        "commodities": {
            "potatoes": {
                "unit": "million cwt",
                "history": {2019: 137, 2020: 142.0, 2021: 139.0, 2022: 140.0, 2023: 139.0, 2024: 142.0},
            },
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 100, 2020: 101.0, 2021: 104.0, 2022: 102.0, 2023: 106.0, 2024: 102.0},
            },
        },
    },
    "illinois": {
        "name": "Illinois",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Illinois/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 2100, 2020: 2158.0, 2021: 2108.0, 2022: 2106.0, 2023: 2090.0, 2024: 2035.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 610, 2020: 624.0, 2021: 612.0, 2022: 632.0, 2023: 661.0, 2024: 691.0},
            },
        },
    },
    "indiana": {
        "name": "Indiana",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Indiana/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 940, 2020: 972.0, 2021: 981.0, 2022: 1025.0, 2023: 1067.0, 2024: 1103.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 330, 2020: 321.0, 2021: 335.0, 2022: 331.0, 2023: 326.0, 2024: 319.0},
            },
        },
    },
    "iowa": {
        "name": "Iowa",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Iowa/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 2500, 2020: 2422.0, 2021: 2350.0, 2022: 2456.0, 2023: 2541.0, 2024: 2598.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 562, 2020: 557.0, 2021: 559.0, 2022: 592.0, 2023: 621.0, 2024: 611.0},
            },
        },
    },
    "kansas": {
        "name": "Kansas",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Kansas/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 334, 2020: 308.0, 2021: 299.0, 2022: 285.0, 2023: 273.0, 2024: 263.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 6350, 2020: 6503.0, 2021: 6247.0, 2022: 5955.0, 2023: 5768.0, 2024: 5826.0},
            },
        },
    },
    "kentucky": {
        "name": "Kentucky",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Kentucky/index.php",
        "commodities": {
            "tobacco": {
                "unit": "million lbs",
                "history": {2019: 82, 2020: 77.0, 2021: 71.7, 2022: 71.0, 2023: 70.8, 2024: 68.1},
            },
            "corn": {
                "unit": "million bushels",
                "history": {2019: 210, 2020: 205.0, 2021: 201.0, 2022: 198.0, 2023: 194.0, 2024: 196.0},
            },
        },
    },
    "louisiana": {
        "name": "Louisiana",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Louisiana/index.php",
        "commodities": {
            "rice": {
                "unit": "million cwt",
                "history": {2019: 32, 2020: 31.3, 2021: 32.3, 2022: 32.6, 2023: 33.4, 2024: 34.2},
            },
            "sugarcane": {
                "unit": "million tons",
                "history": {2019: 15, 2020: 15.3, 2021: 15.8, 2022: 16.7, 2023: 17.4, 2024: 17.4},
            },
        },
    },
    "maine": {
        "name": "Maine",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Maine/index.php",
        "commodities": {
            "potatoes": {
                "unit": "million cwt",
                "history": {2019: 15, 2020: 15.0, 2021: 15.0, 2022: 15.0, 2023: 15.0, 2024: 15.0},
            },
            "blueberries": {
                "unit": "million lbs",
                "history": {2019: 60, 2020: 60.5, 2021: 60.3, 2022: 57.3, 2023: 53.9, 2024: 50.9},
            },
        },
    },
    "maryland": {
        "name": "Maryland",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Maryland/index.php",
        "commodities": {
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 2900, 2020: 2857.0, 2021: 2932.0, 2022: 3031.0, 2023: 2925.0, 2024: 2942.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 26, 2020: 26.0, 2021: 26.0, 2022: 26.0, 2023: 26.0, 2024: 27.0},
            },
        },
    },
    "massachusetts": {
        "name": "Massachusetts",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Massachusetts/index.php",
        "commodities": {
            "cranberries": {
                "unit": "thousand barrels",
                "history": {2019: 1900, 2020: 1923.0, 2021: 1883.0, 2022: 1815.0, 2023: 1841.0, 2024: 1800.0},
            },
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 200, 2020: 199.0, 2021: 191.0, 2022: 183.0, 2023: 177.0, 2024: 181.0},
            },
        },
    },
    "michigan": {
        "name": "Michigan",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Michigan/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 300, 2020: 313.0, 2021: 309.0, 2022: 317.0, 2023: 311.0, 2024: 304.0},
            },
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 11200, 2020: 11117.0, 2021: 10967.0, 2022: 11559.0, 2023: 11938.0, 2024: 12167.0},
            },
        },
    },
    "minnesota": {
        "name": "Minnesota",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Minnesota/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 1450, 2020: 1444.0, 2021: 1464.0, 2022: 1490.0, 2023: 1489.0, 2024: 1537.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 380, 2020: 371.0, 2021: 382.0, 2022: 388.0, 2023: 407.0, 2024: 415.0},
            },
        },
    },
    "mississippi": {
        "name": "Mississippi",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Mississippi/index.php",
        "commodities": {
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 720, 2020: 713.0, 2021: 728.0, 2022: 696.0, 2023: 671.0, 2024: 657.0},
            },
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 5900, 2020: 6067.0, 2021: 5927.0, 2022: 5957.0, 2023: 6171.0, 2024: 5948.0},
            },
        },
    },
    "missouri": {
        "name": "Missouri",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Missouri/index.php",
        "commodities": {
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 275, 2020: 272.0, 2021: 274.0, 2022: 269.0, 2023: 273.0, 2024: 265.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 4300, 2020: 4421.0, 2021: 4388.0, 2022: 4293.0, 2023: 4158.0, 2024: 4105.0},
            },
        },
    },
    "montana": {
        "name": "Montana",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Montana/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 165, 2020: 167.0, 2021: 164.0, 2022: 166.0, 2023: 158.0, 2024: 150.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 2450, 2020: 2426.0, 2021: 2306.0, 2022: 2253.0, 2023: 2171.0, 2024: 2137.0},
            },
        },
    },
    "nebraska": {
        "name": "Nebraska",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Nebraska/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 1780, 2020: 1757.0, 2021: 1782.0, 2022: 1866.0, 2023: 1867.0, 2024: 1890.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 6650, 2020: 6666.0, 2021: 6676.0, 2022: 6486.0, 2023: 6580.0, 2024: 6389.0},
            },
        },
    },
    "nevada": {
        "name": "Nevada",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Nevada/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 445, 2020: 429.0, 2021: 439.0, 2022: 449.0, 2023: 453.0, 2024: 453.0},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 1350, 2020: 1383.0, 2021: 1383.0, 2022: 1324.0, 2023: 1336.0, 2024: 1272.0},
            },
        },
    },
    "new_hampshire": {
        "name": "New Hampshire",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/New_Hampshire/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 65, 2020: 64.0, 2021: 62.0, 2022: 63.0, 2023: 64.0, 2024: 64.0},
            },
            "maple_syrup": {
                "unit": "thousand gallons",
                "history": {2019: 165, 2020: 170.0, 2021: 174.0, 2022: 178.0, 2023: 190.0, 2024: 201.0},
            },
        },
    },
    "new_jersey": {
        "name": "New Jersey",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/New_Jersey/index.php",
        "commodities": {
            "blueberries": {
                "unit": "million lbs",
                "history": {2019: 42, 2020: 42.1, 2021: 42.0, 2022: 42.6, 2023: 43.6, 2024: 42.5},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 90, 2020: 87.0, 2021: 84.0, 2022: 84.0, 2023: 82.0, 2024: 84.0},
            },
        },
    },
    "new_mexico": {
        "name": "New Mexico",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/New_Mexico/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 1350, 2020: 1315.0, 2021: 1280.0, 2022: 1221.0, 2023: 1165.0, 2024: 1132.0},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 780, 2020: 803.0, 2021: 772.0, 2022: 749.0, 2023: 771.0, 2024: 800.0},
            },
        },
    },
    "new_york": {
        "name": "New York",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/New_York/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 15400, 2020: 15227.0, 2021: 14932.0, 2022: 15610.0, 2023: 16007.0, 2024: 16803.0},
            },
            "apples": {
                "unit": "million lbs",
                "history": {2019: 1230, 2020: 1246.0, 2021: 1227.0, 2022: 1208.0, 2023: 1204.0, 2024: 1214.0},
            },
        },
    },
    "north_carolina": {
        "name": "North Carolina",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/North_Carolina/index.php",
        "commodities": {
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 15800, 2020: 15341.0, 2021: 15210.0, 2022: 15447.0, 2023: 15264.0, 2024: 14850.0},
            },
            "hogs": {
                "unit": "thousand head",
                "history": {2019: 9100, 2020: 8938.0, 2021: 9004.0, 2022: 9117.0, 2023: 8984.0, 2024: 9245.0},
            },
        },
    },
    "north_dakota": {
        "name": "North Dakota",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/North_Dakota/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 310, 2020: 314.0, 2021: 319.0, 2022: 314.0, 2023: 311.0, 2024: 305.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 210, 2020: 212.0, 2021: 214.0, 2022: 217.0, 2023: 224.0, 2024: 217.0},
            },
        },
    },
    "ohio": {
        "name": "Ohio",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Ohio/index.php",
        "commodities": {
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 260, 2020: 265.0, 2021: 257.0, 2022: 249.0, 2023: 245.0, 2024: 256.0},
            },
            "corn": {
                "unit": "million bushels",
                "history": {2019: 540, 2020: 552.0, 2021: 553.0, 2022: 533.0, 2023: 542.0, 2024: 545.0},
            },
        },
    },
    "oklahoma": {
        "name": "Oklahoma",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Oklahoma/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 90, 2020: 89.0, 2021: 89.0, 2022: 85.0, 2023: 80.0, 2024: 75.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 5150, 2020: 5205.0, 2021: 5105.0, 2022: 4910.0, 2023: 4907.0, 2024: 4729.0},
            },
        },
    },
    "oregon": {
        "name": "Oregon",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Oregon/index.php",
        "commodities": {
            "hazelnuts": {
                "unit": "million lbs",
                "history": {2019: 55, 2020: 58.6, 2021: 61.1, 2022: 67.0, 2023: 72.3, 2024: 77.2},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 1300, 2020: 1266.0, 2021: 1215.0, 2022: 1213.0, 2023: 1237.0, 2024: 1217.0},
            },
        },
    },
    "pennsylvania": {
        "name": "Pennsylvania",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Pennsylvania/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 10500, 2020: 10886.0, 2021: 10618.0, 2022: 11047.0, 2023: 11315.0, 2024: 11580.0},
            },
            "mushrooms": {
                "unit": "million lbs",
                "history": {2019: 420, 2020: 427.0, 2021: 430.0, 2022: 417.0, 2023: 403.0, 2024: 400.0},
            },
        },
    },
    "rhode_island": {
        "name": "Rhode Island",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Rhode_Island/index.php",
        "commodities": {
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 12, 2020: 12.0, 2021: 12.0, 2022: 11.0, 2023: 11.0, 2024: 11.0},
            },
        },
    },
    "south_carolina": {
        "name": "South Carolina",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/South_Carolina/index.php",
        "commodities": {
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 320, 2020: 326.0, 2021: 321.0, 2022: 311.0, 2023: 295.0, 2024: 278.0},
            },
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 3300, 2020: 3210.0, 2021: 3183.0, 2022: 3120.0, 2023: 3188.0, 2024: 3238.0},
            },
        },
    },
    "south_dakota": {
        "name": "South Dakota",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/South_Dakota/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 780, 2020: 806.0, 2021: 782.0, 2022: 799.0, 2023: 823.0, 2024: 848.0},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 250, 2020: 248.0, 2021: 257.0, 2022: 254.0, 2023: 263.0, 2024: 269.0},
            },
        },
    },
    "tennessee": {
        "name": "Tennessee",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Tennessee/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 1750, 2020: 1778.0, 2021: 1712.0, 2022: 1721.0, 2023: 1755.0, 2024: 1808.0},
            },
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 550, 2020: 523.0, 2021: 523.0, 2022: 527.0, 2023: 530.0, 2024: 518.0},
            },
        },
    },
    "texas": {
        "name": "Texas",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Texas/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 12700, 2020: 12221.0, 2021: 11873.0, 2022: 12220.0, 2023: 12507.0, 2024: 12798.0},
            },
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 4020, 2020: 3762.0, 2021: 3660.0, 2022: 3578.0, 2023: 3385.0, 2024: 3236.0},
            },
        },
    },
    "utah": {
        "name": "Utah",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Utah/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 800, 2020: 826.0, 2021: 814.0, 2022: 841.0, 2023: 850.0, 2024: 857.0},
            },
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 2350, 2020: 2353.0, 2021: 2427.0, 2022: 2422.0, 2023: 2462.0, 2024: 2436.0},
            },
        },
    },
    "vermont": {
        "name": "Vermont",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Vermont/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 2500, 2020: 2401.0, 2021: 2428.0, 2022: 2337.0, 2023: 2395.0, 2024: 2343.0},
            },
            "maple_syrup": {
                "unit": "thousand gallons",
                "history": {2019: 2200, 2020: 2302.0, 2021: 2411.0, 2022: 2413.0, 2023: 2446.0, 2024: 2537.0},
            },
        },
    },
    "virginia": {
        "name": "Virginia",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Virginia/index.php",
        "commodities": {
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 3400, 2020: 3392.0, 2021: 3325.0, 2022: 3424.0, 2023: 3548.0, 2024: 3515.0},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 1450, 2020: 1455.0, 2021: 1446.0, 2022: 1485.0, 2023: 1494.0, 2024: 1459.0},
            },
        },
    },
    "washington": {
        "name": "Washington",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Washington/index.php",
        "commodities": {
            "apples": {
                "unit": "million lbs",
                "history": {2019: 6100, 2020: 6140.0, 2021: 6284.0, 2022: 6048.0, 2023: 5967.0, 2024: 6151.0},
            },
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 145, 2020: 144.0, 2021: 144.0, 2022: 146.0, 2023: 147.0, 2024: 144.0},
            },
        },
    },
    "west_virginia": {
        "name": "West Virginia",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/West_Virginia/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 380, 2020: 387.0, 2021: 381.0, 2022: 390.0, 2023: 372.0, 2024: 363.0},
            },
            "poultry_broilers": {
                "unit": "million lbs",
                "history": {2019: 950, 2020: 972.0, 2021: 987.0, 2022: 964.0, 2023: 1002.0, 2024: 987.0},
            },
        },
    },
    "wisconsin": {
        "name": "Wisconsin",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Wisconsin/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 30600, 2020: 32130.0, 2021: 32418.0, 2022: 31828.0, 2023: 33538.0, 2024: 34858.0},
            },
            "corn": {
                "unit": "million bushels",
                "history": {2019: 500, 2020: 489.0, 2021: 485.0, 2022: 484.0, 2023: 496.0, 2024: 494.0},
            },
        },
    },
    "wyoming": {
        "name": "Wyoming",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Wyoming/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 1300, 2020: 1241.0, 2021: 1219.0, 2022: 1245.0, 2023: 1193.0, 2024: 1172.0},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 1750, 2020: 1710.0, 2021: 1694.0, 2022: 1692.0, 2023: 1714.0, 2024: 1677.0},
            },
        },
    },
}


@dataclass
class CommodityMetric:
    name: str
    unit: str
    history: dict[int, float]
    latest_year: int = 0
    latest_value: float = 0.0
    trend_slope: float = 0.0
    trend_pct: float = 0.0
    forecast_year: int = 0
    forecast_value: float = 0.0


@dataclass
class StateProfile:
    state_id: str
    state_name: str
    dashboard_url: str
    commodities: list[CommodityMetric] = field(default_factory=list)
    production_trend_score: float = 0.0
    data_source: str = ""


@dataclass
class ProductionAssessment:
    grain_output_signal: str
    livestock_output_signal: str
    drought_impact_signal: str
    food_inflation_signal: str
    export_demand_signal: str


@dataclass
class AgricultureReport:
    states: list[StateProfile]
    assessment: ProductionAssessment
    production_trend_score: float
    drought_risk_score: float
    forecast_confidence: float
    trend_label: str
    national_headline: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    top_gainers: list[StateProfile] = field(default_factory=list)
    top_decliners: list[StateProfile] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgricultureExpert(BaseExpert):
    """Expert agriculture agent — USDA NASS state production tracking and forecasting."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="agriculture")
        self.api_key = api_key or os.environ.get("NASS_API_KEY", "") or self._load_config_key()

    def _adjust_market_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        adjusted: list[dict[str, Any]] = []
        for sig in signals:
            row = dict(sig)
            tickers = row.get("tickers") or []
            conf = row.get("confidence")
            if tickers and conf is not None:
                row["confidence"] = self.adjust_signal_confidence(
                    str(tickers[0]), str(row.get("bias", "NEUTRAL")), conf
                )
            adjusted.append(row)
        return adjusted

    @staticmethod
    def _load_config_key() -> str:
        for cfg in (Path("config.json"), Path(__file__).resolve().parents[2] / "config.json"):
            if not cfg.exists():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                return str(data.get("nass_api_key", "") or "")
            except Exception:
                continue
        return ""

    @staticmethod
    def _history_from_quickstats(rows: list[dict[str, Any]]) -> dict[int, float]:
        history: dict[int, float] = {}
        for row in rows:
            year = row.get("year") or row.get("Year")
            value = row.get("Value") or row.get("value")
            try:
                y = int(str(year)[:4])
                v = float(value)
                if v > 0:
                    history[y] = v
            except (TypeError, ValueError):
                continue
        return history

    def _fetch_quickstats(self, state_name: str, commodity_desc: str) -> list[dict[str, Any]]:
        params = {
            "key": self.api_key,
            "source_desc": "SURVEY",
            "commodity_desc": commodity_desc.upper(),
            "state_name": state_name.upper(),
            "agg_level_desc": "STATE",
            "format": "JSON",
        }
        resp = requests.get(QUICKSTATS_API_URL, params=params, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) if isinstance(data, dict) else []

    @staticmethod
    def _linear_trend(history: dict[int, float]) -> tuple[float, int, float]:
        """Least-squares slope/forecast for a year->value series. Returns (slope, next_year, forecast)."""
        years = sorted(history.keys())
        if len(years) < 2:
            year = years[0] if years else datetime.now(timezone.utc).year
            return 0.0, year + 1, history.get(year, 0.0)
        n = len(years)
        mean_x = sum(years) / n
        mean_y = sum(history[y] for y in years) / n
        num = sum((y - mean_x) * (history[y] - mean_y) for y in years)
        den = sum((y - mean_x) ** 2 for y in years)
        slope = num / den if den else 0.0
        intercept = mean_y - slope * mean_x
        next_year = years[-1] + 1
        forecast = slope * next_year + intercept
        return slope, next_year, forecast

    def _build_commodity(self, name: str, cfg: dict[str, Any]) -> CommodityMetric:
        history = {int(y): float(v) for y, v in cfg["history"].items()}
        years = sorted(history.keys())
        latest_year = years[-1]
        latest_value = history[latest_year]
        slope, forecast_year, forecast_value = self._linear_trend(history)
        base_value = history[years[0]]
        trend_pct = round((latest_value - base_value) / base_value * 100, 2) if base_value else 0.0
        return CommodityMetric(
            name=name,
            unit=cfg["unit"],
            history=history,
            latest_year=latest_year,
            latest_value=latest_value,
            trend_slope=round(slope, 3),
            trend_pct=trend_pct,
            forecast_year=forecast_year,
            forecast_value=round(forecast_value, 2),
        )

    def _analyze_state(self, state_id: str, cfg: dict[str, Any]) -> StateProfile:
        source = "Calibrated proxy (set nass_api_key in config.json for live Quick Stats)"
        commodities: list[CommodityMetric] = []
        live_commodity_count = 0

        for name, ccfg in cfg["commodities"].items():
            merged_cfg = dict(ccfg)
            if self.api_key:
                query = NASS_COMMODITY_QUERY.get(name, name.replace("_", " ").upper())
                try:
                    rows = self._fetch_quickstats(cfg["name"], query)
                    live_hist = self._history_from_quickstats(rows)
                    if live_hist:
                        merged_cfg["history"] = {**dict(ccfg.get("history") or {}), **live_hist}
                        live_commodity_count += 1
                except Exception:
                    pass
            commodities.append(self._build_commodity(name, merged_cfg))

        if live_commodity_count:
            source = "USDA NASS Quick Stats API"

        profile = StateProfile(
            state_id=state_id,
            state_name=cfg["name"],
            dashboard_url=cfg["dashboard"],
            commodities=commodities,
            data_source=source,
        )
        self._score_state(profile)
        return profile

    @staticmethod
    def _score_state(profile: StateProfile) -> None:
        if not profile.commodities:
            profile.production_trend_score = 0.5
            return
        pct_changes = [c.trend_pct for c in profile.commodities]
        avg_pct = sum(pct_changes) / len(pct_changes)
        # Map a +/-20% multi-year swing onto a 0-1 band centered on 0.5
        profile.production_trend_score = round(max(0.05, min(0.95, 0.5 + avg_pct / 40.0)), 4)

    def _drought_risk_score(self, states: list[StateProfile]) -> float:
        try:
            from agent_signal_logic import meteorology_agricultural_risk_score

            peer_score = meteorology_agricultural_risk_score()
            if peer_score is not None:
                return round(peer_score, 3)
        except Exception:
            pass
        declining = [s for s in states if s.production_trend_score < 0.45]
        ratio = len(declining) / len(states) if states else 0.0
        return round(max(0.2, min(0.9, 0.35 + ratio * 0.5)), 3)

    def _production_assessment(
        self, states: list[StateProfile], drought_risk: float
    ) -> ProductionAssessment:
        grain_states = [
            s for s in states
            if any(
                c.name in (
                    "corn", "soybeans", "wheat", "cotton", "rice", "peanuts",
                    "potatoes", "tobacco", "sugarcane",
                )
                for c in s.commodities
            )
        ]
        livestock_states = [
            s for s in states
            if any(
                c.name in ("cattle_and_calves", "milk_production", "poultry_broilers", "hogs")
                for c in s.commodities
            )
        ]
        grain_avg = (
            sum(s.production_trend_score for s in grain_states) / len(grain_states)
            if grain_states else 0.5
        )
        livestock_avg = (
            sum(s.production_trend_score for s in livestock_states) / len(livestock_states)
            if livestock_states else 0.5
        )

        grain_signal = (
            "grain output expanding — corn/soy/wheat belts trending up"
            if grain_avg >= 0.6
            else "grain output contracting — yield pressure across monitored belts"
            if grain_avg <= 0.4
            else "grain output roughly stable"
        )
        livestock_signal = (
            "herd/dairy output expanding — feedlot and dairy supply building"
            if livestock_avg >= 0.6
            else "herd/dairy output contracting — culling and drought-driven liquidation risk"
            if livestock_avg <= 0.4
            else "herd/dairy output stable"
        )
        drought_signal = (
            "elevated drought stress — yield and herd-size downside risk across ag belts"
            if drought_risk >= 0.6
            else "moderate drought exposure — localized yield variability"
            if drought_risk >= 0.45
            else "low drought stress — favorable growing conditions"
        )
        food_inflation = (
            "supply tightness raises food-price pass-through risk"
            if (grain_avg <= 0.42 or livestock_avg <= 0.42) and drought_risk >= 0.55
            else "food-price pressure contained by adequate supply"
        )
        export_demand = (
            "export-ready surplus supports trade flow"
            if grain_avg >= 0.6
            else "export volumes constrained by softer output"
            if grain_avg <= 0.4
            else "export demand steady"
        )

        return ProductionAssessment(
            grain_output_signal=grain_signal,
            livestock_output_signal=livestock_signal,
            drought_impact_signal=drought_signal,
            food_inflation_signal=food_inflation,
            export_demand_signal=export_demand,
        )

    def _market_signals(
        self,
        assessment: ProductionAssessment,
        *,
        production_trend_score: float,
        trend_label: str,
        drought_risk_score: float,
        forecast_confidence: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import agriculture_market_impact_signals

        signals = agriculture_market_impact_signals(
            production_trend_score=production_trend_score,
            trend_label=trend_label,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
            grain_output_strong="expanding" in assessment.grain_output_signal,
            livestock_output_strong="expanding" in assessment.livestock_output_signal,
            food_inflation_pressure="tightness" in assessment.food_inflation_signal,
        )
        return self._adjust_market_signals(signals)

    @staticmethod
    def _recommendations(
        top_gainers: list[StateProfile],
        top_decliners: list[StateProfile],
        assessment: ProductionAssessment,
        production_trend_score: float,
        drought_risk_score: float,
    ) -> list[str]:
        recs = [
            f"Production trend: {production_trend_score:.2f} | Drought risk: {drought_risk_score:.2f}",
            f"Grain: {assessment.grain_output_signal}",
            f"Livestock/dairy: {assessment.livestock_output_signal}",
            f"Drought impact: {assessment.drought_impact_signal}",
            f"Food inflation: {assessment.food_inflation_signal}",
            f"Export demand: {assessment.export_demand_signal}",
        ]

        def _state_line(s: StateProfile) -> str:
            parts = ", ".join(
                f"{c.name} {c.latest_value:g} {c.unit} ({c.trend_pct:+.1f}%, "
                f"{c.forecast_year} forecast {c.forecast_value:g})"
                for c in s.commodities
            )
            return f"{s.state_name}: {parts}"

        if top_gainers:
            recs.append("Top gaining states: " + "; ".join(_state_line(s) for s in top_gainers))
        if top_decliners:
            recs.append("Top declining states: " + "; ".join(_state_line(s) for s in top_decliners))
        if production_trend_score >= 0.65:
            recs.append("Strong production trend — favorable for agribusiness input demand")
        if drought_risk_score >= 0.6:
            recs.append("Elevated drought risk — monitor crop insurance and yield revisions")
        return recs

    def _expert_summary(
        self,
        states: list[StateProfile],
        assessment: ProductionAssessment,
        production_trend_score: float,
        trend_label: str,
        drought_risk_score: float,
        top_gainers: list[StateProfile],
        top_decliners: list[StateProfile],
    ) -> str:
        movers_line = ""
        if top_gainers or top_decliners:
            gainer_names = ", ".join(s.state_name for s in top_gainers)
            decliner_names = ", ".join(s.state_name for s in top_decliners)
            movers_line = (
                f" Top gainers: {gainer_names or 'n/a'}. "
                f"Top decliners: {decliner_names or 'n/a'}."
            )
        return (
            f"USDA NASS production analysis — national trend {trend_label.lower()} "
            f"(score {production_trend_score:.2f}) across {len(states)} states, "
            f"drought risk {drought_risk_score:.2f}.{movers_line} "
            f"Grain: {assessment.grain_output_signal}. "
            f"Livestock/dairy: {assessment.livestock_output_signal}. "
            f"Drought: {assessment.drought_impact_signal}. "
            f"Food inflation: {assessment.food_inflation_signal}."
        )

    def analyze(self) -> AgricultureReport:
        states: list[StateProfile] = []
        for state_id, cfg in STATES.items():
            states.append(self._analyze_state(state_id, cfg))
            time.sleep(0.1)

        production_trend_score = round(
            sum(s.production_trend_score for s in states) / len(states), 4
        )
        drought_risk_score = self._drought_risk_score(states)
        forecast_confidence = round(max(0.3, min(0.85, 0.55 + (0.5 - drought_risk_score) * 0.4)), 3)

        trend_label = (
            "Strong Growth" if production_trend_score >= 0.68 else
            "Growth" if production_trend_score >= 0.55 else
            "Stable" if production_trend_score >= 0.45 else
            "Contraction" if production_trend_score >= 0.32 else
            "Sharp Contraction"
        )

        assessment = self._production_assessment(states, drought_risk_score)
        ranked = sorted(states, key=lambda s: s.production_trend_score, reverse=True)
        top_gainers = ranked[:3]
        top_decliners = list(reversed(ranked[-3:]))
        sources = sorted({s.data_source for s in states if s.data_source})

        summary = self._expert_summary(
            states, assessment, production_trend_score, trend_label, drought_risk_score,
            top_gainers, top_decliners,
        )
        signals = self._market_signals(
            assessment,
            production_trend_score=production_trend_score,
            trend_label=trend_label,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
        )
        recs = self._recommendations(
            top_gainers, top_decliners, assessment, production_trend_score, drought_risk_score
        )

        headline = (
            f"National agricultural production trend {trend_label.lower()} "
            f"(score {production_trend_score:.2f}); drought risk {drought_risk_score:.2f}"
        )

        return AgricultureReport(
            states=states,
            assessment=assessment,
            production_trend_score=production_trend_score,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
            trend_label=trend_label,
            national_headline=headline,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            top_gainers=top_gainers,
            top_decliners=top_decliners,
            data_sources=sources,
        )

    @staticmethod
    def state_catalog() -> list[dict[str, Any]]:
        return [
            {
                "id": state_id,
                "name": cfg["name"],
                "dashboard": cfg["dashboard"],
                "commodities": list(cfg["commodities"].keys()),
            }
            for state_id, cfg in STATES.items()
        ]

    def to_dict(self, report: AgricultureReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Agriculture Expert",
                "state_directory": NASS_STATE_DIRECTORY_URL,
                "analyzed_at": report.analyzed_at,
                "national_headline": report.national_headline,
                "expert_summary": report.expert_summary,
                "states_monitored": len(report.states),
                "data_sources": report.data_sources,
            },
            "top_gainers": [
                {
                    "id": s.state_id,
                    "name": s.state_name,
                    "dashboard": s.dashboard_url,
                    "production_trend_score": s.production_trend_score,
                    "data_source": s.data_source,
                    "commodities": [
                        {
                            "name": c.name,
                            "unit": c.unit,
                            "history": {str(y): v for y, v in c.history.items()},
                            "latest_year": c.latest_year,
                            "latest_value": c.latest_value,
                            "trend_pct": c.trend_pct,
                            "forecast_year": c.forecast_year,
                            "forecast_value": c.forecast_value,
                        }
                        for c in s.commodities
                    ],
                }
                for s in report.top_gainers
            ],
            "top_decliners": [
                {
                    "id": s.state_id,
                    "name": s.state_name,
                    "dashboard": s.dashboard_url,
                    "production_trend_score": s.production_trend_score,
                    "data_source": s.data_source,
                    "commodities": [
                        {
                            "name": c.name,
                            "unit": c.unit,
                            "history": {str(y): v for y, v in c.history.items()},
                            "latest_year": c.latest_year,
                            "latest_value": c.latest_value,
                            "trend_pct": c.trend_pct,
                            "forecast_year": c.forecast_year,
                            "forecast_value": c.forecast_value,
                        }
                        for c in s.commodities
                    ],
                }
                for s in report.top_decliners
            ],
            "assessment": {
                "grain_output_signal": a.grain_output_signal,
                "livestock_output_signal": a.livestock_output_signal,
                "drought_impact_signal": a.drought_impact_signal,
                "food_inflation_signal": a.food_inflation_signal,
                "export_demand_signal": a.export_demand_signal,
            },
            "states": [
                {
                    "id": s.state_id,
                    "name": s.state_name,
                    "dashboard": s.dashboard_url,
                    "data_source": s.data_source,
                    "production_trend_score": s.production_trend_score,
                    "commodities": [
                        {
                            "name": c.name,
                            "unit": c.unit,
                            "latest_year": c.latest_year,
                            "latest_value": c.latest_value,
                            "trend_pct": c.trend_pct,
                            "forecast_year": c.forecast_year,
                            "forecast_value": c.forecast_value,
                        }
                        for c in s.commodities
                    ],
                }
                for s in report.states
            ],
            "metrics": {
                "production_trend_score": report.production_trend_score,
                "drought_risk_score": report.drought_risk_score,
                "forecast_confidence": report.forecast_confidence,
                "trend_label": report.trend_label,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "nass_state_catalog.json"
            catalog_path.write_text(
                json.dumps(self.state_catalog(), indent=2),
                encoding="utf-8",
            )
        return result


def run_agriculture_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return AgricultureExpert(pipeline_context=pipeline_context).run(output=output)
