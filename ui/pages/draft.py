import streamlit as st

st.title("Draft Analysis")
st.markdown("Projected season-long fantasy value to guide draft decisions.")

# TODO: load player data
# TODO: exclude keepers (see src/keepers.py, data/raw/keepers.csv) -- or just load
#       data/processed/draft_rankings.csv if main.py's `draft` command already did this
# TODO: build draft features
# TODO: run draft model predictions
# TODO: display ranked player table with projected points
