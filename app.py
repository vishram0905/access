"""ACCESS web app.  Run:  streamlit run app.py"""
import streamlit as st

from access.ui import PAGES

st.set_page_config(page_title="ACCESS · Research funding finder", page_icon="🎓", layout="wide",
                   initial_sidebar_state="collapsed")
nav = st.navigation([st.Page(path, title=title, default=(i == 0)) for i, (path, title) in enumerate(PAGES)],
                    position="hidden")
st.session_state["current_page"] = nav.title  # read by access.ui.setup() to underline the active menu item
nav.run()
