"""
World city pool for random lead search rotation.
High-PPP English-speaking markets are listed first and weighted 2x.
Used by both autopilot scheduler and the manual search random button.
"""
import random

# ── Tier 1: English-speaking, high-PPP, best conversion (weighted 2x) ──────
TIER1 = [
    # USA
    "New York, NY, USA", "Los Angeles, CA, USA", "Chicago, IL, USA",
    "Houston, TX, USA", "Phoenix, AZ, USA", "Philadelphia, PA, USA",
    "San Antonio, TX, USA", "San Diego, CA, USA", "Dallas, TX, USA",
    "San Jose, CA, USA", "Austin, TX, USA", "Jacksonville, FL, USA",
    "Fort Worth, TX, USA", "Columbus, OH, USA", "Charlotte, NC, USA",
    "Indianapolis, IN, USA", "San Francisco, CA, USA", "Seattle, WA, USA",
    "Denver, CO, USA", "Nashville, TN, USA", "Oklahoma City, OK, USA",
    "El Paso, TX, USA", "Washington, DC, USA", "Las Vegas, NV, USA",
    "Louisville, KY, USA", "Memphis, TN, USA", "Portland, OR, USA",
    "Baltimore, MD, USA", "Milwaukee, WI, USA", "Albuquerque, NM, USA",
    "Tucson, AZ, USA", "Fresno, CA, USA", "Sacramento, CA, USA",
    "Mesa, AZ, USA", "Omaha, NE, USA", "Cleveland, OH, USA",
    "Atlanta, GA, USA", "Raleigh, NC, USA", "Miami, FL, USA",
    "Minneapolis, MN, USA", "Tampa, FL, USA", "New Orleans, LA, USA",
    "Arlington, TX, USA", "Bakersfield, CA, USA", "Aurora, CO, USA",
    "Anaheim, CA, USA", "Santa Ana, CA, USA", "Corpus Christi, TX, USA",
    "Riverside, CA, USA", "Lexington, KY, USA", "St. Louis, MO, USA",
    "Pittsburgh, PA, USA", "Anchorage, AK, USA", "Stockton, CA, USA",
    "Cincinnati, OH, USA", "St. Paul, MN, USA", "Toledo, OH, USA",
    "Greensboro, NC, USA", "Newark, NJ, USA", "Plano, TX, USA",
    "Henderson, NV, USA", "Lincoln, NE, USA", "Buffalo, NY, USA",
    "Fort Wayne, IN, USA", "Jersey City, NJ, USA", "Chula Vista, CA, USA",
    "Orlando, FL, USA", "St. Petersburg, FL, USA", "Norfolk, VA, USA",
    "Chandler, AZ, USA", "Laredo, TX, USA", "Madison, WI, USA",
    "Durham, NC, USA", "Lubbock, TX, USA", "Winston-Salem, NC, USA",
    "Garland, TX, USA", "Glendale, AZ, USA", "Hialeah, FL, USA",
    "Reno, NV, USA", "Baton Rouge, LA, USA", "Irvine, CA, USA",
    "Chesapeake, VA, USA", "Scottsdale, AZ, USA", "North Las Vegas, NV, USA",
    "Fremont, CA, USA", "Gilbert, AZ, USA", "San Bernardino, CA, USA",
    "Birmingham, AL, USA", "Rochester, NY, USA", "Richmond, VA, USA",
    # Canada
    "Toronto, Ontario, Canada", "Vancouver, BC, Canada", "Calgary, Alberta, Canada",
    "Edmonton, Alberta, Canada", "Ottawa, Ontario, Canada", "Montreal, Quebec, Canada",
    "Winnipeg, Manitoba, Canada", "Quebec City, Quebec, Canada", "Hamilton, Ontario, Canada",
    "London, Ontario, Canada", "Halifax, Nova Scotia, Canada", "Victoria, BC, Canada",
    "Kitchener, Ontario, Canada", "Saskatoon, Saskatchewan, Canada", "Regina, Saskatchewan, Canada",
    "Kelowna, BC, Canada", "Abbotsford, BC, Canada", "Windsor, Ontario, Canada",
    # UK
    "London, UK", "Manchester, UK", "Birmingham, UK", "Leeds, UK",
    "Glasgow, UK", "Sheffield, UK", "Bradford, UK", "Liverpool, UK",
    "Edinburgh, UK", "Bristol, UK", "Cardiff, Wales, UK", "Coventry, UK",
    "Nottingham, UK", "Leicester, UK", "Southampton, UK", "Portsmouth, UK",
    "Aberdeen, UK", "Brighton, UK", "Hull, UK", "Plymouth, UK",
    "Belfast, Northern Ireland, UK", "Derby, UK", "Reading, UK", "Northampton, UK",
    # Australia
    "Sydney, NSW, Australia", "Melbourne, VIC, Australia", "Brisbane, QLD, Australia",
    "Perth, WA, Australia", "Adelaide, SA, Australia", "Gold Coast, QLD, Australia",
    "Canberra, ACT, Australia", "Newcastle, NSW, Australia", "Sunshine Coast, QLD, Australia",
    "Wollongong, NSW, Australia", "Hobart, TAS, Australia", "Geelong, VIC, Australia",
    "Townsville, QLD, Australia", "Cairns, QLD, Australia", "Darwin, NT, Australia",
    # New Zealand
    "Auckland, New Zealand", "Wellington, New Zealand", "Christchurch, New Zealand",
    "Hamilton, New Zealand", "Tauranga, New Zealand", "Dunedin, New Zealand",
    # Ireland
    "Dublin, Ireland", "Cork, Ireland", "Limerick, Ireland", "Galway, Ireland",
    # Singapore
    "Singapore",
    # UAE (English-friendly)
    "Dubai, UAE", "Abu Dhabi, UAE", "Sharjah, UAE",
    # South Africa (English)
    "Johannesburg, South Africa", "Cape Town, South Africa", "Durban, South Africa",
    "Pretoria, South Africa", "Port Elizabeth, South Africa",
]

# ── Tier 2: Non-English but wealthy / high-spending markets ────────────────
TIER2 = [
    # Germany
    "Berlin, Germany", "Munich, Germany", "Hamburg, Germany", "Cologne, Germany",
    "Frankfurt, Germany", "Stuttgart, Germany", "Dusseldorf, Germany", "Dortmund, Germany",
    "Leipzig, Germany", "Bremen, Germany", "Dresden, Germany", "Nuremberg, Germany",
    # France
    "Paris, France", "Marseille, France", "Lyon, France", "Toulouse, France",
    "Nice, France", "Nantes, France", "Strasbourg, France", "Montpellier, France",
    "Bordeaux, France", "Lille, France",
    # Netherlands
    "Amsterdam, Netherlands", "Rotterdam, Netherlands", "The Hague, Netherlands",
    "Utrecht, Netherlands", "Eindhoven, Netherlands",
    # Spain
    "Madrid, Spain", "Barcelona, Spain", "Valencia, Spain", "Seville, Spain",
    "Zaragoza, Spain", "Bilbao, Spain", "Malaga, Spain", "Alicante, Spain",
    # Italy
    "Rome, Italy", "Milan, Italy", "Naples, Italy", "Turin, Italy",
    "Palermo, Italy", "Genoa, Italy", "Florence, Italy", "Venice, Italy",
    "Bologna, Italy", "Catania, Italy",
    # Portugal
    "Lisbon, Portugal", "Porto, Portugal", "Braga, Portugal",
    # Scandinavia
    "Stockholm, Sweden", "Gothenburg, Sweden", "Malmo, Sweden",
    "Oslo, Norway", "Bergen, Norway",
    "Copenhagen, Denmark", "Aarhus, Denmark",
    "Helsinki, Finland",
    # Switzerland
    "Zurich, Switzerland", "Geneva, Switzerland", "Basel, Switzerland",
    # Austria
    "Vienna, Austria", "Graz, Austria",
    # Belgium
    "Brussels, Belgium", "Antwerp, Belgium",
    # Poland
    "Warsaw, Poland", "Krakow, Poland", "Lodz, Poland", "Wroclaw, Poland",
    "Poznan, Poland", "Gdansk, Poland",
    # Czech Republic
    "Prague, Czech Republic", "Brno, Czech Republic",
    # Hungary
    "Budapest, Hungary",
    # Romania
    "Bucharest, Romania", "Cluj-Napoca, Romania",
    # Turkey
    "Istanbul, Turkey", "Ankara, Turkey", "Izmir, Turkey",
    "Antalya, Turkey", "Bursa, Turkey",
    # Brazil
    "São Paulo, Brazil", "Rio de Janeiro, Brazil", "Brasilia, Brazil",
    "Salvador, Brazil", "Fortaleza, Brazil", "Curitiba, Brazil",
    "Manaus, Brazil", "Recife, Brazil", "Porto Alegre, Brazil",
    # Mexico
    "Mexico City, Mexico", "Guadalajara, Mexico", "Monterrey, Mexico",
    "Puebla, Mexico", "Tijuana, Mexico", "Juarez, Mexico", "Merida, Mexico",
    # Argentina
    "Buenos Aires, Argentina", "Cordoba, Argentina", "Rosario, Argentina",
    "Mendoza, Argentina",
    # Chile
    "Santiago, Chile", "Valparaiso, Chile",
    # Colombia
    "Bogota, Colombia", "Medellin, Colombia", "Cali, Colombia",
    # Japan
    "Tokyo, Japan", "Osaka, Japan", "Nagoya, Japan", "Sapporo, Japan",
    "Fukuoka, Japan", "Kobe, Japan", "Kyoto, Japan",
    # South Korea
    "Seoul, South Korea", "Busan, South Korea", "Incheon, South Korea",
    # Malaysia
    "Kuala Lumpur, Malaysia", "Penang, Malaysia", "Johor Bahru, Malaysia",
    # Thailand
    "Bangkok, Thailand", "Phuket, Thailand", "Chiang Mai, Thailand",
    # Philippines
    "Manila, Philippines", "Cebu City, Philippines", "Davao City, Philippines",
    # Indonesia
    "Jakarta, Indonesia", "Surabaya, Indonesia", "Bandung, Indonesia",
    "Medan, Indonesia", "Yogyakarta, Indonesia",
    # India
    "Mumbai, India", "Delhi, India", "Bangalore, India", "Hyderabad, India",
    "Chennai, India", "Kolkata, India", "Pune, India", "Ahmedabad, India",
    "Jaipur, India", "Surat, India", "Lucknow, India", "Kanpur, India",
    "Nagpur, India", "Indore, India", "Thane, India", "Bhopal, India",
    "Visakhapatnam, India", "Pimpri-Chinchwad, India", "Patna, India", "Vadodara, India",
    # China (many businesses have bad websites)
    "Shanghai, China", "Beijing, China", "Guangzhou, China", "Shenzhen, China",
    "Chengdu, China", "Hangzhou, China", "Wuhan, China", "Xi'an, China",
    # Russia
    "Moscow, Russia", "Saint Petersburg, Russia", "Novosibirsk, Russia",
    # Egypt
    "Cairo, Egypt", "Alexandria, Egypt", "Giza, Egypt",
    # Nigeria
    "Lagos, Nigeria", "Abuja, Nigeria", "Port Harcourt, Nigeria",
    # Kenya
    "Nairobi, Kenya", "Mombasa, Kenya",
    # Ghana
    "Accra, Ghana",
    # Israel
    "Tel Aviv, Israel", "Jerusalem, Israel", "Haifa, Israel",
    # Saudi Arabia
    "Riyadh, Saudi Arabia", "Jeddah, Saudi Arabia", "Mecca, Saudi Arabia",
    # Kuwait
    "Kuwait City, Kuwait",
    # Qatar
    "Doha, Qatar",
    # Bahrain
    "Manama, Bahrain",
]

# Combined weighted pool: Tier1 appears twice for 2x probability
_POOL = TIER1 + TIER1 + TIER2


def random_location() -> str:
    """Return a random city from the worldwide pool (Tier1 weighted 2x)."""
    return random.choice(_POOL)


def random_locations(n: int = 5, unique: bool = True) -> list[str]:
    """Return n random cities. If unique=True, no duplicates."""
    if unique:
        return random.sample(_POOL, min(n, len(_POOL)))
    return [random.choice(_POOL) for _ in range(n)]


def all_locations() -> list[str]:
    """Return all unique locations sorted alphabetically."""
    return sorted(set(TIER1 + TIER2))
