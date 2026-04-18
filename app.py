import streamlit as st
import swisseph as swe
import datetime
from geopy.geocoders import Nominatim
import pytz
from timezonefinder import TimezoneFinder
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
st.set_page_config(page_title="Horary Astrologer", page_icon="✨", layout="wide")

# Configure Gemini API
try:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        st.error("GEMINI_API_KEY not found. Please set it in your .env file or GitHub Secrets.")
        st.stop()
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro')
except Exception as e:
    st.error(f"Failed to configure Gemini API: {e}. Check your API key and internet connection.")
    st.stop()


# --- Helper Functions ---
def get_sign_and_degree(longitude):
    """Converts a longitude (0-360) to a zodiac sign and degree within that sign."""
    if not isinstance(longitude, (int, float)):
        return "N/A"
    
    # Ensure longitude is within 0-360
    longitude = longitude % 360
    if longitude < 0:
        longitude += 360

    signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
    sign_index = int(longitude / 30)
    sign_name = signs[sign_index]
    degree_in_sign = longitude % 30
    return f"{degree_in_sign:.2f}° {sign_name}"

def get_planet_by_house_ruler(house_num, cusps, planets_data, sign_rulers):
    """Determines the ruler of a given house based on its cusp sign."""
    cusp_longitude = cusps[house_num]
    sign_index = int(cusp_longitude / 30)
    sign_name = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"][sign_index]
    
    # Traditional Rulers mapping
    ruler = sign_rulers.get(sign_name)
    
    if ruler:
        # Find the planet's actual position
        for planet_name, details in planets_data.items():
            if planet_name.lower() == ruler.lower():
                return planet_name, details['longitude'], sign_name
    return None, None, sign_name

def calculate_aspects(lon1, lon2):
    """Calculates the closest major Ptolemaic aspect between two longitudes."""
    diff = abs(lon1 - lon2)
    diff = diff % 360 # Normalize to 0-360
    
    # Consider shorter distance for opposition
    if diff > 180:
        diff = 360 - diff

    aspects = {
        0: "Conjunction",
        60: "Sextile",
        90: "Square",
        120: "Trine",
        180: "Opposition"
    }
    
    # Check for aspects with a small orb (e.g., 5-7 degrees)
    orb = 7 # Define an orb for aspect detection
    
    for degree, name in aspects.items():
        if abs(diff - degree) <= orb:
            return name
    return None

def is_applying(lon1_deg, speed1, lon2_deg, speed2, aspect_deg, orb):
    """
    Checks if planet 1 is applying to an aspect with planet 2.
    Assumes standard direct motion unless speed indicates retrograde.
    """
    target_lon_plus = (lon1_deg + aspect_deg) % 360
    target_lon_minus = (lon1_deg - aspect_deg + 360) % 360

    # Determine if planet 1 is closing in on planet 2
    # Simple check for now: if difference is reducing, it's applying
    current_diff = (lon2_deg - lon1_deg + 360) % 360
    
    # Predict next step
    next_lon1 = (lon1_deg + speed1 / 24) % 360 # speed is per day
    next_lon2 = (lon2_deg + speed2 / 24) % 360

    next_diff = (next_lon2 - next_lon1 + 360) % 360

    # If the aspect is within orb and getting closer
    if abs(current_diff - aspect_deg) <= orb and abs(next_diff - aspect_deg) < abs(current_diff - aspect_deg):
        return True

    return False

# --- Main Streamlit App ---
st.title("✨ The Horary Tutor ✨")
st.markdown("---")
st.write("Welcome to your Horary Journal. Let's cast a chart for your question.")

# --- Session State Initialization ---
# This ensures data persists across reruns
if 'chart_data' not in st.session_state:
    st.session_state.chart_data = None
if 'querent_significator' not in st.session_state:
    st.session_state.querent_significator = None
if 'quesited_significator' not in st.session_state:
    st.session_state.quesited_significator = None
if 'question_text' not in st.session_state:
    st.session_state.question_text = ""
if 'house_options' not in st.session_state:
    st.session_state.house_options = {
        1: "1st House: Querent's body, life, appearance, self-interest",
        2: "2nd House: Money, possessions, movable goods, resources",
        3: "3rd House: Siblings, short journeys, neighbors, letters, news",
        4: "4th House: Father, home, real estate, buried treasure, end of matter",
        5: "5th House: Children, pleasure, speculation, gambling, love affairs",
        6: "6th House: Sickness, servants, small animals, labor, work conditions",
        7: "7th House: Partner, marriage, open enemies, lawsuits, strangers",
        8: "8th House: Death, legacies, spouse's money, taxes, deep fears",
        9: "9th House: Long journeys, religion, philosophy, law, dreams, higher education",
        10: "10th House: Mother, career, reputation, honor, government",
        11: "11th House: Friends, hopes, wishes, allies, good fortune",
        12: "12th House: Secret enemies, self-undoing, prisons, hospitals, hidden things"
    }

# --- Phase 1: Moment of Crystallization ---
st.header("1. The Moment of Crystallization")

col1, col2 = st.columns(2)
with col1:
    date_input = st.date_input("Date the question was understood", datetime.date.today())
with col2:
    time_input = st.time_input("Time (Local Time)", datetime.datetime.now().time())

location_input = st.text_input("Location (e.g., London, UK or New York, NY)", "New York, NY")
user_question = st.text_area("What is the exact question you are asking?", st.session_state.question_text)
st.session_state.question_text = user_question # Save to session state

if st.button("Cast the Heavens & Identify Significators"):
    if not user_question:
        st.error("Please enter a question to cast the chart!")
        st.stop()
        
    geolocator = Nominatim(user_agent="horary_app")
    location = geolocator.geocode(location_input)
    
    if not location:
        st.error(f"Could not find location: {location_input}. Please try a major city nearby.")
        st.stop()

    lat = location.latitude
    lon = location.longitude

    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    
    if tz_name is None:
        st.error(f"Could not determine timezone for {location_input}. Please try a different city or check the spelling.")
        st.stop()

    local_tz = pytz.timezone(tz_name)
    local_datetime = datetime.datetime.combine(date_input, time_input)
    
    try:
        localized_datetime = local_tz.localize(local_datetime, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        st.warning("Ambiguous time detected (e.g., during DST change). Adjusting to earlier valid time.")
        localized_datetime = local_tz.localize(local_datetime, is_dst=False)
    except pytz.exceptions.NonExistentTimeError:
        st.error("Non-existent time detected (e.g., during DST jump). Please adjust your local time.")
        st.stop()

    utc_datetime = localized_datetime.astimezone(pytz.utc)

    # --- ASTROLOGY MATH ---
    hour_decimal_utc = utc_datetime.hour + (utc_datetime.minute / 60.0)
    julian_day = swe.julday(utc_datetime.year, utc_datetime.month, utc_datetime.day, hour_decimal_utc)
    
    try:
        cusps_output, ascmc_output = swe.houses(julian_day, lat, lon, b'R')
        ascendant_longitude = ascmc_output[0] # Ascendant
        
        # Calculate planet positions
        planets_data = {}
        planet_ids = {
            "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, 
            "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN
        }
        
        for p_name, p_id in planet_ids.items():
            xx, retflag = swe.calc_ut(julian_day, p_id)
            planets_data[p_name] = {
                'longitude': xx[0],
                'speed': xx[3] # Daily speed
            }

        st.session_state.chart_data = {
            "julian_day": julian_day,
            "lat": lat,
            "lon": lon,
            "utc_datetime": utc_datetime,
            "location_name": location.address,
            "ascendant_longitude": ascendant_longitude,
            "cusps": cusps_output,
            "planets": planets_data,
            "question": user_question
        }
        st.success(f"Chart successfully cast for {utc_datetime.strftime('%Y-%m-%d %H:%M UTC')} in {location.address}.")
        st.toast("Chart Calculated!", icon="🎉")

    except Exception as e:
        st.error(f"Error calculating chart: {e}. Please check your date/time/location or try again.")
        st.session_state.chart_data = None
        st.stop()

# Display chart data if available
if st.session_state.chart_data:
    chart_data = st.session_state.chart_data
    
    st.subheader(f"Chart for: {chart_data['question']}")
    st.markdown(f"**Location:** {chart_data['location_name']}")
    st.markdown(f"**UTC Time:** {chart_data['utc_datetime'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    st.markdown(f"**Ascendant:** **{get_sign_and_degree(chart_data['ascendant_longitude'])}**")
    
    st.subheader("Planetary Positions:")
    for planet, data in chart_data['planets'].items():
        st.write(f"- {planet}: {get_sign_and_degree(data['longitude'])} (Speed: {data['speed']:.2f}°/day)")

    st.subheader("House Cusps (Regiomontanus):")
    for i in range(1, 13):
        if i < len(chart_data['cusps']) and isinstance(chart_data['cusps'][i], (int, float)):
            st.write(f"House {i}: {get_sign_and_degree(chart_data['cusps'][i])}")
        else:
            st.warning(f"Could not retrieve House {i} cusp data.")

    st.markdown("---")

    # --- Phase 2: Assigning Significators ---
    st.header("2. Assigning Significators")
    st.write("Now, let's identify the Querent and the Quesited based on your question.")
    
    st.markdown(f"**Querent (You) is represented by:**")
    st.markdown(f"- **The Ascendant:** **{get_sign_and_degree(chart_data['ascendant_longitude'])}**")
    
    # Identify the ruler of the Ascendant
    asc_sign_index = int(chart_data['ascendant_longitude'] / 30)
    asc_sign_name = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"][asc_sign_index]

    traditional_rulers = {
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
        "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars", # Old ruler Pluto isn't traditional
        "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", # Old ruler Uranus isn't traditional
        "Pisces": "Jupiter" # Old ruler Neptune isn't traditional
    }
    
    asc_ruler_name = traditional_rulers.get(asc_sign_name)
    asc_ruler_lon = chart_data['planets'].get(asc_ruler_name, {}).get('longitude')
    
    st.markdown(f"- **Its Ruler:** **{asc_ruler_name}** at **{get_sign_and_degree(asc_ruler_lon)}**")
    
    st.session_state.querent_significator = {
        "planet": asc_ruler_name,
        "longitude": asc_ruler_lon,
        "speed": chart_data['planets'].get(asc_ruler_name, {}).get('speed', 0),
        "sign": asc_sign_name,
        "house_cusp": chart_data['cusps'][1] # 1st House Cusp
    }

    st.markdown("---")
    st.markdown(f"**Question:** *'{chart_data['question']}'*")
    st.write("Which house best signifies the **Quesited** (the subject of your question)?")
    
    quesited_house_choice = st.selectbox(
        "Select the house that represents the Quesited:",
        options=list(st.session_state.house_options.keys()),
        format_func=lambda x: st.session_state.house_options[x],
        key="quesited_house_selector" # Unique key for selectbox
    )
    
    if quesited_house_choice:
        st.info(f"You have selected the {quesited_house_choice}th House for the Quesited.")
        
        # Identify the ruler of the Quesited House
        quesited_house_cusp_lon = chart_data['cusps'][quesited_house_choice]
        quesited_sign_index = int(quesited_house_cusp_lon / 30)
        quesited_sign_name = signs[quesited_sign_index]
        
        quesited_ruler_name = traditional_rulers.get(quesited_sign_name)
        quesited_ruler_lon = chart_data['planets'].get(quesited_ruler_name, {}).get('longitude')

        st.markdown(f"**Quesited is represented by:**")
        st.markdown(f"- Its House Cusp: **{get_sign_and_degree(quesited_house_cusp_lon)}**")
        st.markdown(f"- Its Ruler: **{quesited_ruler_name}** at **{get_sign_and_degree(quesited_ruler_lon)}**")

        st.session_state.quesited_significator = {
            "planet": quesited_ruler_name,
            "longitude": quesited_ruler_lon,
            "speed": chart_data['planets'].get(quesited_ruler_name, {}).get('speed', 0),
            "sign": quesited_sign_name,
            "house_cusp": quesited_house_cusp_lon
        }
        
        st.markdown("---")
        
        # --- Phase 3: Conversation about Aspects (AI Integration) ---
        st.header("3. Analyzing Aspects with Gemini AI")
        
        querent_planet = st.session_state.querent_significator
        quesited_planet = st.session_state.quesited_significator

        if querent_planet and quesited_planet:
            st.write(f"Querent: **{querent_planet['planet']}** ({get_sign_and_degree(querent_planet['longitude'])})")
            st.write(f"Quesited: **{quesited_planet['planet']}** ({get_sign_and_degree(quesited_planet['longitude'])})")

            # Calculate actual aspects
            querent_lon = querent_planet['longitude']
            quesited_lon = quesited_planet['longitude']
            
            aspect_type = calculate_aspects(querent_lon, quesited_lon)
            
            # Simple apply/separate for now (more complex logic needed for full horary)
            apply_or_separate = "applying" # Placeholder for now, requires more complex logic
            
            if aspect_type:
                st.info(f"An **{aspect_type}** aspect is formed between the Querent's and Quesited's significators.")
                
                # AI Chat for Aspect Interpretation
                st.subheader("Gemini AI's Interpretation:")
                
                # Check if a chat history exists in session state
                if "gemini_chat_history" not in st.session_state:
                    st.session_state.gemini_chat_history = []
                
                # Build the initial prompt for Gemini
                if not st.session_state.gemini_chat_history:
                    initial_prompt = f"""
                    You are a highly knowledgeable and traditional Horary Astrologer, deeply familiar with the rules of William Lilly.
                    A querent has asked: "{chart_data['question']}"
                    The chart was cast for {chart_data['utc_datetime'].strftime('%Y-%m-%d %H:%M UTC')} in {chart_data['location_name']}.
                    The Ascendant is {get_sign_and_degree(chart_data['ascendant_longitude'])}.
                    The Querent is signified by {querent_planet['planet']} at {get_sign_and_degree(querent_planet['longitude'])}.
                    The Quesited is signified by {quesited_planet['planet']} at {get_sign_and_degree(quesited_planet['longitude'])}, representing the {quesited_house_choice}th house.
                    These two significators are forming an **{aspect_type}** aspect.
                    Please begin a conversation with the querent by first explaining the basic meaning of this aspect in horary, and then ask a follow-up question to guide their understanding. Keep your response concise, professional, and in the tone of a traditional astrologer.
                    """
                    st.session_state.gemini_chat_history.append({"role": "user", "parts": [initial_prompt]})
                    
                    try:
                        response = model.generate_content(initial_prompt)
                        st.session_state.gemini_chat_history.append({"role": "model", "parts": [response.text]})
                    except Exception as e:
                        st.error(f"Gemini AI Error: {e}")
                        st.session_state.gemini_chat_history = [] # Reset on error

                # Display chat history
                for message in st.session_state.gemini_chat_history:
                    with st.chat_message(message["role"]):
                        st.markdown(message["parts"][0])
                
                # Chat input for user
                user_chat_input = st.chat_input("Continue the conversation...")
                if user_chat_input:
                    st.session_state.gemini_chat_history.append({"role": "user", "parts": [user_chat_input]})
                    with st.chat_message("user"):
                        st.markdown(user_chat_input)
                    
                    try:
                        response = model.generate_content(st.session_state.gemini_chat_history)
                        st.session_state.gemini_chat_history.append({"role": "model", "parts": [response.text]})
                        with st.chat_message("model"):
                            st.markdown(response.text)
                    except Exception as e:
                        st.error(f"Gemini AI Error: {e}")
                        st.session_state.gemini_chat_history = [] # Reset on error
            else:
                st.warning("No major Ptolemaic aspect found between the significators (within a 7° orb).")
                st.write("*(Here, a Gemini AI Agent would discuss strictures against judgment or the lack of connection.)*")

        else:
            st.warning("Significators not fully identified yet.")
    
    st.markdown("---")
    st.info("Remember to always verify the data with trusted ephemeris and astrological tables.")

else:
    st.error("Could not find that location. Please try a major city nearby.")