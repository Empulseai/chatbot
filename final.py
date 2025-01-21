import streamlit as st
import pandas as pd
import spacy
import re
import pyodbc
from datetime import datetime
import speech_recognition as sr
from gtts import gTTS
import os
import tempfile


# Load SpaCy NLP model
@st.cache_resource
def load_spacy_model():
    try:
        return spacy.load("en_core_web_sm")
    except OSError as e:
        st.warning("SpaCy model 'en_core_web_sm' not found. Attempting to download...")
        try:
            spacy.cli.download("en_core_web_sm")
            return spacy.load("en_core_web_sm")
        except Exception as download_error:
            st.error("Failed to download the SpaCy model 'en_core_web_sm'. Please install it manually using 'python -m spacy download en_core_web_sm'.")
            raise download_error

# # Retrieve database configuration from secrets
# database_server = st.secrets["general"]["database_server"]
# database_name = st.secrets["general"]["database_name"]

# # Database connection string
# connection_string = (
#     f'DRIVER={{ODBC Driver 17 for SQL Server}};'
#     f'SERVER={database_server};'
#     f'DATABASE={database_name};'
#     'Trusted_Connection=yes'
# )



# Database connection string
connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=BNGEMPL101\\SQLEXPRESS;'
    'DATABASE=Db_FireSandop_Live;'
    'Trusted_Connection=yes'
)


# Database function to execute stored procedure
def execute_stored_procedure(connection_string, procedure_name):
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        cursor.execute(f"EXEC {procedure_name}")
        results = []

        # Handle multiple result sets
        while True:
            if cursor.description:
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                df = pd.DataFrame.from_records(rows, columns=columns)
                results.append(df)
            if not cursor.nextset():
                break

        return results if results else None

    except Exception as e:
        st.error(f"Database error: {e}")
        return None
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()


# Function to handle speech-to-text
def speech_to_text():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        st.info("Listening... Please speak now.")
        try:
            audio = recognizer.listen(source, timeout=5)
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            st.warning("Could not understand your speech. Please try again.")
        except sr.RequestError as e:
            st.error(f"Speech recognition error: {e}")
        except Exception as e:
            st.error(f"An error occurred: {e}")
    return ""


# Function to convert text to speech
def text_to_speech(response_text):
    try:
        tts = gTTS(text=response_text, lang='en')
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
            tts.save(temp_audio.name)
            st.audio(temp_audio.name, format="audio/mp3")
            os.unlink(temp_audio.name)
    except Exception as e:
        st.error(f"Error generating audio: {e}")


# App title
st.title("Delivery Date Finder with Speech and Text Input")

# Load SpaCy model
try:
    nlp = load_spacy_model()
except Exception:
    nlp = None

# Check if data is already loaded into session state
if "data" not in st.session_state:
    # Fetch data from the database if not already loaded
    procedure_name = "dbo.USP_MasterSchedule_Select_new_Python"
    dataframes = execute_stored_procedure(connection_string, procedure_name)

    if dataframes:
        st.session_state.data = dataframes[0]
        st.write("Data loaded from the database:")
        st.write(st.session_state.data.head(20))
    else:
        st.error("Failed to load data from the database.")
else:
    # Data already loaded
    st.write("Data already loaded from the database:")
    st.write(st.session_state.data.head(20))

# Unified input for question
st.write("Ask your question below:")
question = st.text_input("Type your question or click the microphone button to speak:")

# Button for speech-to-text
if st.button("🎤 Speak"):
    detected_speech = speech_to_text()
    if detected_speech:
        question = detected_speech
        st.text_input("Your question (detected from speech):", value=question, key="speech_result")

if question:
    try:
        # Process the question using NLP to extract meaningful keywords
        doc = nlp(question.lower())
        keywords = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN", "NUM"] or token.text.lower() in ["serial", "pump", "tank", "body", "chassis"]]

        # Check if the query contains a valid SO number
        so_number_pattern = r"\b(?:SO[-\s]?)?(\d{6,})\b"
        so_number_match = re.search(so_number_pattern, question, re.IGNORECASE)

        if so_number_match:
            so_number = so_number_match.group(1)

            # Filter the dataset by SO number
            so_result = st.session_state.data[st.session_state.data['soNumber'].astype(str).str.contains(so_number, case=False, na=False)]

            if not so_result.empty:
                if any(keyword in keywords for keyword in ["serial", "pump", "tank", "body", "chassis"]):
                    serial_number_columns = {
                        "pump": "Pump SN_AX",
                        "tank": "Tank SN_AX",
                        "body": "Body SN_AX",
                        "chassis": "Chassis_ST"
                    }

                    component_found = None
                    for component, column_name in serial_number_columns.items():
                        if component in question.lower():
                            component_found = component
                            break

                    if component_found:
                        column_name = serial_number_columns[component_found]
                        if column_name in so_result.columns:
                            serial_numbers = so_result[column_name].dropna().tolist()
                            if serial_numbers:
                                response_text = f"{component_found.capitalize()} serial numbers for SO number {so_number}: {', '.join(map(str, serial_numbers))}"
                            else:
                                response_text = f"No {component_found} serial numbers found for SO number {so_number}."
                        else:
                            response_text = f"Column '{column_name}' not found in the dataset."
                    else:
                        response_text = "Component not found in the query. Please specify pump, tank, body, or chassis."
                elif "delivery" in keywords and "date" in keywords:
                    if 'deliveryDate' in so_result.columns:
                        # delivery_dates = so_result['deliveryDate'].tolist()
                        delivery_dates = so_result['deliveryDate'].dt.strftime('%Y-%m-%d').tolist()  # Convert to string format
                        response_text = f"Delivery dates for SO number {so_number}: {', '.join(delivery_dates)}"
                    else:
                        response_text = "Column 'deliveryDate' not found in the dataset."
                elif "dealer" in keywords:
                    if 'dealerName' in so_result.columns:
                        dealers = so_result['dealerName'].dropna().unique()
                        if dealers.size > 0:
                            response_text = f"Dealer(s) for SO number {so_number}: {', '.join(dealers)}"
                        else:
                            response_text = f"No dealer information found for SO number {so_number}."
                    else:
                        response_text = "Column 'dealerName' not found in the dataset."
                else:
                    response_text = "Query unclear. Please ask about serial numbers, dealers, or delivery dates."
            else:
                response_text = f"No information found for SO number {so_number}."
        else:
            response_text = "The query does not contain a valid SO number. Please try again with a valid format (e.g., 'SO-123456' or '123456')."

        st.success(response_text)
        text_to_speech(response_text)

    except Exception as e:
        st.error(f"An error occurred: {e}")
