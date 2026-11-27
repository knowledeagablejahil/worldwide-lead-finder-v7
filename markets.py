"""Worldwide city centres to avoid heavy public geocoding requests.
Coordinates are approximate city centres, not precise business locations.
"""
MARKETS = {
    "United Kingdom": {"country_code": "GB", "cities": {"London": (51.5074, -0.1278), "Manchester": (53.4808, -2.2426), "Birmingham": (52.4862, -1.8904), "Leeds": (53.8008, -1.5491), "Bristol": (51.4545, -2.5879)}},
    "Germany": {"country_code": "DE", "cities": {"Berlin": (52.5200, 13.4050), "Munich": (48.1351, 11.5820), "Frankfurt": (50.1109, 8.6821), "Hamburg": (53.5511, 9.9937), "Cologne": (50.9375, 6.9603)}},
    "France": {"country_code": "FR", "cities": {"Paris": (48.8566, 2.3522), "Lyon": (45.7640, 4.8357), "Nice": (43.7102, 7.2620), "Marseille": (43.2965, 5.3698), "Bordeaux": (44.8378, -0.5792)}},
    "Netherlands": {"country_code": "NL", "cities": {"Amsterdam": (52.3676, 4.9041), "Rotterdam": (51.9244, 4.4777), "Utrecht": (52.0907, 5.1214), "The Hague": (52.0705, 4.3007)}},
    "Switzerland": {"country_code": "CH", "cities": {"Zurich": (47.3769, 8.5417), "Geneva": (46.2044, 6.1432), "Zug": (47.1662, 8.5155), "Lausanne": (46.5197, 6.6323)}},
    "Italy": {"country_code": "IT", "cities": {"Milan": (45.4642, 9.1900), "Rome": (41.9028, 12.4964), "Turin": (45.0703, 7.6869), "Bologna": (44.4949, 11.3426)}},
    "Spain": {"country_code": "ES", "cities": {"Madrid": (40.4168, -3.7038), "Barcelona": (41.3874, 2.1686), "Marbella": (36.5101, -4.8824), "Valencia": (39.4699, -0.3763)}},
    "Belgium": {"country_code": "BE", "cities": {"Brussels": (50.8503, 4.3517), "Antwerp": (51.2194, 4.4025), "Ghent": (51.0543, 3.7174)}},
    "Ireland": {"country_code": "IE", "cities": {"Dublin": (53.3498, -6.2603), "Cork": (51.8985, -8.4756), "Galway": (53.2707, -9.0568)}},
    "Austria": {"country_code": "AT", "cities": {"Vienna": (48.2082, 16.3738), "Graz": (47.0707, 15.4395), "Salzburg": (47.8095, 13.0550)}},
    "Portugal": {"country_code": "PT", "cities": {"Lisbon": (38.7223, -9.1393), "Porto": (41.1579, -8.6291), "Cascais": (38.6979, -9.4215)}},
    "Poland": {"country_code": "PL", "cities": {"Warsaw": (52.2297, 21.0122), "Krakow": (50.0647, 19.9450), "Wroclaw": (51.1079, 17.0385)}},
    "Sweden": {"country_code": "SE", "cities": {"Stockholm": (59.3293, 18.0686), "Gothenburg": (57.7089, 11.9746), "Malmo": (55.6050, 13.0038)}},
    "Denmark": {"country_code": "DK", "cities": {"Copenhagen": (55.6761, 12.5683), "Aarhus": (56.1629, 10.2039), "Odense": (55.4038, 10.4024)}},
    "Norway": {"country_code": "NO", "cities": {"Oslo": (59.9139, 10.7522), "Bergen": (60.3913, 5.3221), "Stavanger": (58.9700, 5.7331)}},
    "Finland": {"country_code": "FI", "cities": {"Helsinki": (60.1699, 24.9384), "Espoo": (60.2055, 24.6559), "Tampere": (61.4978, 23.7610)}},
    "Czech Republic": {"country_code": "CZ", "cities": {"Prague": (50.0755, 14.4378), "Brno": (49.1951, 16.6068)}},
    "Romania": {"country_code": "RO", "cities": {"Bucharest": (44.4268, 26.1025), "Cluj-Napoca": (46.7712, 23.6236), "Timisoara": (45.7489, 21.2087)}},
    "Cyprus": {"country_code": "CY", "cities": {"Limassol": (34.7071, 33.0226), "Nicosia": (35.1856, 33.3823), "Larnaca": (34.9167, 33.6362)}},
    "Malta": {"country_code": "MT", "cities": {"Valletta": (35.8992, 14.5141), "Sliema": (35.9122, 14.5041), "St Julian's": (35.9181, 14.4898)}},
    "Greece": {"country_code": "GR", "cities": {"Athens": (37.9838, 23.7275), "Thessaloniki": (40.6401, 22.9444)}},
    "Luxembourg": {"country_code": "LU", "cities": {"Luxembourg City": (49.6116, 6.1319)}},
    "Hungary": {"country_code": "HU", "cities": {"Budapest": (47.4979, 19.0402), "Debrecen": (47.5316, 21.6273)}},
    "Estonia": {"country_code": "EE", "cities": {"Tallinn": (59.4370, 24.7536), "Tartu": (58.3776, 26.7290)}},
    "Lithuania": {"country_code": "LT", "cities": {"Vilnius": (54.6872, 25.2797), "Kaunas": (54.8985, 23.9036)}},
}


# Additional market centres are approximate and intended only for city-radius searches.
# UAE is deliberately excluded: outreach is for firms outside the UAE.
ADDITIONAL_MARKETS = {
    # Europe (including additional EU markets and neighbouring non-EU markets)
    "Latvia": ("Europe", "LV", {"Riga": (56.9496,24.1052), "Daugavpils": (55.8714,26.5161)}),
    "Slovakia": ("Europe", "SK", {"Bratislava": (48.1486,17.1077), "Kosice": (48.7164,21.2611)}),
    "Slovenia": ("Europe", "SI", {"Ljubljana": (46.0569,14.5058), "Maribor": (46.5547,15.6459)}),
    "Croatia": ("Europe", "HR", {"Zagreb": (45.8150,15.9819), "Split": (43.5081,16.4402)}),
    "Bulgaria": ("Europe", "BG", {"Sofia": (42.6977,23.3219), "Plovdiv": (42.1354,24.7453)}),
    "Serbia": ("Europe", "RS", {"Belgrade": (44.7866,20.4489), "Novi Sad": (45.2671,19.8335)}),
    "Albania": ("Europe", "AL", {"Tirana": (41.3275,19.8187), "Durres": (41.3231,19.4414)}),
    "Iceland": ("Europe", "IS", {"Reykjavik": (64.1466,-21.9426)}),
    # Americas
    "United States": ("North America", "US", {"New York": (40.7128,-74.0060), "Miami": (25.7617,-80.1918), "Chicago": (41.8781,-87.6298), "Houston": (29.7604,-95.3698), "Los Angeles": (34.0522,-118.2437)}),
    "Canada": ("North America", "CA", {"Toronto": (43.6532,-79.3832), "Vancouver": (49.2827,-123.1207), "Montreal": (45.5019,-73.5674), "Calgary": (51.0447,-114.0719)}),
    "Mexico": ("North America", "MX", {"Mexico City": (19.4326,-99.1332), "Monterrey": (25.6866,-100.3161), "Guadalajara": (20.6597,-103.3496)}),
    "Costa Rica": ("North America", "CR", {"San Jose": (9.9281,-84.0907)}),
    "Panama": ("North America", "PA", {"Panama City": (8.9824,-79.5199)}),
    "Brazil": ("South America", "BR", {"Sao Paulo": (-23.5505,-46.6333), "Rio de Janeiro": (-22.9068,-43.1729), "Brasilia": (-15.7939,-47.8828)}),
    "Argentina": ("South America", "AR", {"Buenos Aires": (-34.6037,-58.3816), "Cordoba": (-31.4201,-64.1888)}),
    "Chile": ("South America", "CL", {"Santiago": (-33.4489,-70.6693), "Valparaiso": (-33.0472,-71.6127)}),
    "Colombia": ("South America", "CO", {"Bogota": (4.7110,-74.0721), "Medellin": (6.2442,-75.5812), "Cali": (3.4516,-76.5320)}),
    "Peru": ("South America", "PE", {"Lima": (-12.0464,-77.0428), "Arequipa": (-16.4090,-71.5375)}),
    "Uruguay": ("South America", "UY", {"Montevideo": (-34.9011,-56.1645), "Punta del Este": (-34.9667,-54.9500)}),
    "Ecuador": ("South America", "EC", {"Quito": (-0.1807,-78.4678), "Guayaquil": (-2.1709,-79.9224)}),
    # Asia-Pacific
    "India": ("Asia", "IN", {"Mumbai": (19.0760,72.8777), "New Delhi": (28.6139,77.2090), "Bengaluru": (12.9716,77.5946), "Hyderabad": (17.3850,78.4867), "Ahmedabad": (23.0225,72.5714)}),
    "Pakistan": ("Asia", "PK", {"Karachi": (24.8607,67.0011), "Lahore": (31.5204,74.3587), "Islamabad": (33.6844,73.0479)}),
    "Bangladesh": ("Asia", "BD", {"Dhaka": (23.8103,90.4125), "Chattogram": (22.3569,91.7832)}),
    "Singapore": ("Asia", "SG", {"Singapore": (1.3521,103.8198)}),
    "Hong Kong": ("Asia", "HK", {"Central": (22.2819,114.1587), "Kowloon": (22.3193,114.1694)}),
    "China": ("Asia", "CN", {"Shanghai": (31.2304,121.4737), "Shenzhen": (22.5431,114.0579), "Guangzhou": (23.1291,113.2644), "Beijing": (39.9042,116.4074)}),
    "Japan": ("Asia", "JP", {"Tokyo": (35.6762,139.6503), "Osaka": (34.6937,135.5023), "Nagoya": (35.1815,136.9066)}),
    "South Korea": ("Asia", "KR", {"Seoul": (37.5665,126.9780), "Busan": (35.1796,129.0756)}),
    "Taiwan": ("Asia", "TW", {"Taipei": (25.0330,121.5654), "Kaohsiung": (22.6273,120.3014)}),
    "Indonesia": ("Asia", "ID", {"Jakarta": (-6.2088,106.8456), "Surabaya": (-7.2575,112.7521), "Bandung": (-6.9175,107.6191)}),
    "Malaysia": ("Asia", "MY", {"Kuala Lumpur": (3.1390,101.6869), "George Town": (5.4141,100.3288), "Johor Bahru": (1.4927,103.7414)}),
    "Thailand": ("Asia", "TH", {"Bangkok": (13.7563,100.5018), "Chiang Mai": (18.7883,98.9853), "Phuket": (7.8804,98.3923)}),
    "Vietnam": ("Asia", "VN", {"Ho Chi Minh City": (10.8231,106.6297), "Hanoi": (21.0278,105.8342), "Da Nang": (16.0544,108.2022)}),
    "Philippines": ("Asia", "PH", {"Manila": (14.5995,120.9842), "Makati": (14.5547,121.0244), "Cebu City": (10.3157,123.8854)}),
    "Sri Lanka": ("Asia", "LK", {"Colombo": (6.9271,79.8612), "Kandy": (7.2906,80.6337)}),
    "Nepal": ("Asia", "NP", {"Kathmandu": (27.7172,85.3240), "Pokhara": (28.2096,83.9856)}),
    "Kazakhstan": ("Asia", "KZ", {"Almaty": (43.2389,76.8897), "Astana": (51.1694,71.4491)}),
    "Uzbekistan": ("Asia", "UZ", {"Tashkent": (41.2995,69.2401), "Samarkand": (39.6542,66.9597)}),
    "Georgia": ("Asia", "GE", {"Tbilisi": (41.7151,44.8271), "Batumi": (41.6168,41.6367)}),
    "Armenia": ("Asia", "AM", {"Yerevan": (40.1792,44.4991)}),
    "Azerbaijan": ("Asia", "AZ", {"Baku": (40.4093,49.8671)}),
    # Middle East & North Africa
    "Saudi Arabia": ("Middle East & North Africa", "SA", {"Riyadh": (24.7136,46.6753), "Jeddah": (21.4858,39.1925), "Dammam": (26.4207,50.0888)}),
    "Oman": ("Middle East & North Africa", "OM", {"Muscat": (23.5880,58.3829), "Sohar": (24.3410,56.7295)}),
    "Qatar": ("Middle East & North Africa", "QA", {"Doha": (25.2854,51.5310)}),
    "Bahrain": ("Middle East & North Africa", "BH", {"Manama": (26.2285,50.5860)}),
    "Kuwait": ("Middle East & North Africa", "KW", {"Kuwait City": (29.3759,47.9774)}),
    "Egypt": ("Middle East & North Africa", "EG", {"Cairo": (30.0444,31.2357), "Alexandria": (31.2001,29.9187)}),
    "Jordan": ("Middle East & North Africa", "JO", {"Amman": (31.9539,35.9106), "Irbid": (32.5556,35.8500)}),
    "Turkey": ("Middle East & North Africa", "TR", {"Istanbul": (41.0082,28.9784), "Ankara": (39.9334,32.8597), "Izmir": (38.4237,27.1428)}),
    "Morocco": ("Middle East & North Africa", "MA", {"Casablanca": (33.5731,-7.5898), "Rabat": (34.0209,-6.8416), "Marrakesh": (31.6295,-7.9811)}),
    "Tunisia": ("Middle East & North Africa", "TN", {"Tunis": (36.8065,10.1815), "Sfax": (34.7406,10.7603)}),
    "Lebanon": ("Middle East & North Africa", "LB", {"Beirut": (33.8938,35.5018)}),
    # Sub-Saharan Africa
    "South Africa": ("Sub-Saharan Africa", "ZA", {"Johannesburg": (-26.2041,28.0473), "Cape Town": (-33.9249,18.4241), "Durban": (-29.8587,31.0218)}),
    "Nigeria": ("Sub-Saharan Africa", "NG", {"Lagos": (6.5244,3.3792), "Abuja": (9.0765,7.3986)}),
    "Kenya": ("Sub-Saharan Africa", "KE", {"Nairobi": (-1.2921,36.8219), "Mombasa": (-4.0435,39.6682)}),
    "Ghana": ("Sub-Saharan Africa", "GH", {"Accra": (5.6037,-0.1870), "Kumasi": (6.6885,-1.6244)}),
    "Mauritius": ("Sub-Saharan Africa", "MU", {"Port Louis": (-20.1609,57.5012), "Ebene": (-20.2435,57.4888)}),
    "Rwanda": ("Sub-Saharan Africa", "RW", {"Kigali": (-1.9441,30.0619)}),
    "Uganda": ("Sub-Saharan Africa", "UG", {"Kampala": (0.3476,32.5825)}),
    "Tanzania": ("Sub-Saharan Africa", "TZ", {"Dar es Salaam": (-6.7924,39.2083), "Arusha": (-3.3869,36.6830)}),
    "Ethiopia": ("Sub-Saharan Africa", "ET", {"Addis Ababa": (9.0300,38.7400)}),
    "Senegal": ("Sub-Saharan Africa", "SN", {"Dakar": (14.7167,-17.4677)}),
    "Ivory Coast": ("Sub-Saharan Africa", "CI", {"Abidjan": (5.3600,-4.0083)}),
    "Zambia": ("Sub-Saharan Africa", "ZM", {"Lusaka": (-15.3875,28.3228)}),
    # Oceania
    "Australia": ("Oceania", "AU", {"Sydney": (-33.8688,151.2093), "Melbourne": (-37.8136,144.9631), "Brisbane": (-27.4698,153.0251), "Perth": (-31.9505,115.8605)}),
    "New Zealand": ("Oceania", "NZ", {"Auckland": (-36.8509,174.7645), "Wellington": (-41.2865,174.7767), "Christchurch": (-43.5321,172.6362)}),
}

for country, (region, code, cities) in ADDITIONAL_MARKETS.items():
    MARKETS[country] = {"country_code": code, "region": region, "cities": cities}
for country in MARKETS:
    MARKETS[country].setdefault("region", "Europe")
REGIONS = ["Europe", "North America", "South America", "Asia",
           "Middle East & North Africa", "Sub-Saharan Africa", "Oceania"]


CATEGORIES = {
    "Company Formation & Corporate Services": ["consulting", "business_consultant", "consultant"],
    # Backward compatibility: existing V2–V5 runs contain the old category key.
    # The V6 interface hides it and new runs do NOT save generic consultants.
    "Business Consultants": ["consulting", "business_consultant", "consultant"],
    "Accounting Firms": ["accountant", "tax_advisor", "tax_adviser"],
    "Real Estate Agencies": ["estate_agent", "real_estate"],
    "Law Firms": ["lawyer"],
}
