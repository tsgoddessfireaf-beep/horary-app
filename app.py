import streamlit as st

st.set_page_config(page_title="Horary Astrologer", page_icon="✨")

st.title("✨ The Horary Tutor ✨")
st.write("Welcome to your Horary Journal. The heavens are ready.")

if st.button("Crystallize Question"):
    st.success("The exact moment has been recorded!")
    