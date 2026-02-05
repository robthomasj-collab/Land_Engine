import streamlit as st
from streamlit_folium import st_folium
import folium
from typing import Dict, Any, Tuple


# -----------------------------
# Page config & global styling
# -----------------------------

st.set_page_config(
    page_title="Land Suitability Engine",
    layout="wide",
)

# Dark / Bloomberg-style theme via CSS overrides
st.markdown(
    """
    <style>
    body {
        background-color: #050608;
        color: #e5e7eb;
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1.5rem;
        max-width: 1400px;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #050608 0%, #111827 100%);
        border-right: 1px solid #1f2933;
    }
    [data-testid="stMetricValue"] {
        color: #f9fafb;
    }
    [data-testid="stMetricDelta"] {
        color: #22c55e;
    }
    .suitability-pill {
        padding: 0.15rem 0.65rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #f9fafb;
        background: #111827;
        border: 1px solid #374151;
    }
    .parcel-header {
        font-weight: 600;
        font-size: 0.9rem;
        color: #e5e7eb;
        margin-bottom: 0.1rem;
    }
    .pill-high { background: #166534 !important; }
    .pill-medium { background: #9a3412 !important; }
    .pill-low { background: #7f1d1d !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Static TAP data
# -----------------------------

ParcelScores = Dict[str, Any]

TAP_DATA: Dict[str, ParcelScores] = {
    "Rosemount – Utility-Ready Parcel": {
        "city": "Rosemount, MN",
        "lat": 44.739,
        "lon": -93.093,
        # Raw factor scores are already 0–100, higher is better
        "power_dist": 92,
        "fiber_dist": 88,
        "water_access": 85,
        "highway_access": 78,
        "rail_access": 60,
        "solar_potential": 74,
        "wind_potential": 58,
        "flood_zone_bool": False,
        "historical_contamination": 15,  # lower is better, will be inverted
        "council_sentiment": 82,
    },
    "Farmington – Emerging Industrial Parcel": {
        "city": "Farmington, MN",
        "lat": 44.637,
        "lon": -93.145,
        "power_dist": 80,
        "fiber_dist": 75,
        "water_access": 72,
        "highway_access": 82,
        "rail_access": 68,
        "solar_potential": 79,
        "wind_potential": 65,
        "flood_zone_bool": True,
        "historical_contamination": 28,
        "council_sentiment": 70,
    },
    "Becker – Legacy Generation Parcel": {
        "city": "Becker, MN",
        "lat": 45.392,
        "lon": -93.871,
        "power_dist": 96,
        "fiber_dist": 70,
        "water_access": 90,
        "highway_access": 88,
        "rail_access": 92,
        "solar_potential": 69,
        "wind_potential": 83,
        "flood_zone_bool": False,
        "historical_contamination": 40,
        "council_sentiment": 76,
    },
}


# -----------------------------
# Persona definitions
# -----------------------------

PERSONA_WEIGHTS = {
    "Data Center": {
        "power": 10,
        "fiber": 9,
        "water": 5,
        "highway": 4,
        "rail": 2,
        "solar": 5,
        "wind": 2,
        "flood_risk": 9,
        "sentiment": 7,
    },
    "Industrial": {
        "power": 8,
        "fiber": 6,
        "water": 7,
        "highway": 9,
        "rail": 8,
        "solar": 3,
        "wind": 3,
        "flood_risk": 7,
        "sentiment": 6,
    },
    "Solar": {
        "power": 4,
        "fiber": 3,
        "water": 4,
        "highway": 5,
        "rail": 3,
        "solar": 10,
        "wind": 7,
        "flood_risk": 10,
        "sentiment": 6,
    },
}


def ensure_slider_state_for_persona(persona: str) -> None:
    """Initialize or reset slider state based on selected persona."""
    weights = PERSONA_WEIGHTS[persona]
    for key, val in weights.items():
        state_key = f"w_{key}"
        if state_key not in st.session_state:
            st.session_state[state_key] = val


def apply_persona(persona: str) -> None:
    """Force-reset sliders to persona weights."""
    weights = PERSONA_WEIGHTS[persona]
    for key, val in weights.items():
        st.session_state[f"w_{key}"] = val


def simulate_sentiment_score(text: str) -> int:
    """
    Lightweight stand‑in for an LLM-based council sentiment scraper.
    Maps language to a 0–100 sentiment suitability score.
    """
    if not text or not text.strip():
        return 50

    t = text.lower()
    positive_words = [
        "support",
        "in favor",
        "approve",
        "opportunity",
        "jobs",
        "investment",
        "strategic",
        "tax base",
    ]
    negative_words = [
        "oppose",
        "against",
        "concern",
        "delay",
        "litigation",
        "moratorium",
        "protest",
        "traffic",
        "pollution",
    ]

    pos_hits = sum(t.count(w) for w in positive_words)
    neg_hits = sum(t.count(w) for w in negative_words)

    base = 50 + 10 * (pos_hits - neg_hits)
    return int(max(0, min(100, base)))


def compute_parcel_score(
    parcel: ParcelScores,
    weights: Dict[str, float],
    flood_risk_slider: int,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute global suitability score (0–100) with:
    - zero‑out gate on high flood risk aversion
    - weighted, normalized factors
    """
    flood_zone = parcel["flood_zone_bool"]

    # Zero-out gate: if user is very flood-averse and parcel is in flood zone.
    if flood_risk_slider >= 7 and flood_zone:
        return 0.0, {}

    # Factor normalization: all input scores are 0–100,
    # but we invert "bad" contamination to become a positive signal.
    power = parcel["power_dist"]
    fiber = parcel["fiber_dist"]
    water = parcel["water_access"]
    highway = parcel["highway_access"]
    rail = parcel["rail_access"]
    solar = parcel["solar_potential"]
    wind = parcel["wind_potential"]
    contamination = 100 - parcel["historical_contamination"]
    sentiment = parcel["council_sentiment"]

    factor_scores = {
        "Power": power,
        "Fiber": fiber,
        "Water": water,
        "Highway": highway,
        "Rail": rail,
        "Solar GHI": solar,
        "Wind": wind,
        "Low Flood Exposure": 100 if not flood_zone else max(0, 100 - 10 * flood_risk_slider),
        "Clean History": contamination,
        "Council Sentiment": sentiment,
    }

    # Map factor labels to slider-weight keys
    weight_mapping = {
        "Power": "power",
        "Fiber": "fiber",
        "Water": "water",
        "Highway": "highway",
        "Rail": "rail",
        "Solar GHI": "solar",
        "Wind": "wind",
        "Low Flood Exposure": "flood_risk",
        "Council Sentiment": "sentiment",
        "Clean History": "sentiment",  # contamination contributes to "friction" bucket
    }

    weighted_sum = 0.0
    total_weight = 0.0
    factor_contributions: Dict[str, float] = {}

    for label, raw in factor_scores.items():
        key = weight_mapping[label]
        w = weights.get(key, 0.0)
        if w <= 0:
            continue
        contribution = raw * w
        weighted_sum += contribution
        total_weight += w * 100  # max factor value
        factor_contributions[label] = contribution

    if total_weight == 0:
        return 0.0, factor_contributions

    score_0_100 = 100.0 * weighted_sum / total_weight
    return score_0_100, factor_contributions


def score_to_bucket(score: float) -> str:
    if score >= 75:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def bucket_to_class(score: float) -> str:
    if score >= 75:
        return "pill-high"
    if score >= 50:
        return "pill-medium"
    return "pill-low"


def render_sidebar() -> Dict[str, float]:
    st.sidebar.title("Suitability Controls")

    # Persona + preset handling
    persona = st.sidebar.selectbox(
        "Persona",
        options=list(PERSONA_WEIGHTS.keys()),
        key="persona",
    )

    # Initialize slider state on first load for this persona
    ensure_slider_state_for_persona(persona)

    # Optional "reset" button to re-apply institutional weights
    if st.sidebar.button("Reset to Institutional Weights"):
        apply_persona(persona)
        st.experimental_rerun()

    st.sidebar.markdown("---")

    # Utilities
    st.sidebar.subheader("Utilities")
    w_power = st.sidebar.slider(
        "Power",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_power", PERSONA_WEIGHTS[persona]["power"]),
        key="w_power",
    )
    w_fiber = st.sidebar.slider(
        "Fiber",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_fiber", PERSONA_WEIGHTS[persona]["fiber"]),
        key="w_fiber",
    )
    w_water = st.sidebar.slider(
        "Water",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_water", PERSONA_WEIGHTS[persona]["water"]),
        key="w_water",
    )

    # Logistics
    st.sidebar.subheader("Logistics")
    w_highway = st.sidebar.slider(
        "Highway",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_highway", PERSONA_WEIGHTS[persona]["highway"]),
        key="w_highway",
    )
    w_rail = st.sidebar.slider(
        "Rail",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_rail", PERSONA_WEIGHTS[persona]["rail"]),
        key="w_rail",
    )

    # Environment
    st.sidebar.subheader("Environment")
    w_solar = st.sidebar.slider(
        "Solar GHI",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_solar", PERSONA_WEIGHTS[persona]["solar"]),
        key="w_solar",
    )
    w_wind = st.sidebar.slider(
        "Wind",
        min_value=0,
        max_value=10,
        value=st.session_state.get("w_wind", PERSONA_WEIGHTS[persona]["wind"]),
        key="w_wind",
    )
    w_flood_risk = st.sidebar.slider(
        "Flood Risk (aversion)",
        min_value=0,
        max_value=10,
        value=st.session_state.get(
            "w_flood_risk", PERSONA_WEIGHTS[persona]["flood_risk"]
        ),
        key="w_flood_risk",
        help="Higher = less tolerance for flood risk. Drives zero-out gate.",
    )

    # Sentiment group (slider controlled or AI-updated)
    st.sidebar.subheader("Sentiment")
    w_sentiment = st.sidebar.slider(
        "Public / Political Friction (weight)",
        min_value=0,
        max_value=10,
        value=st.session_state.get(
            "w_sentiment", PERSONA_WEIGHTS[persona]["sentiment"]
        ),
        key="w_sentiment",
        help="How much council sentiment & historical friction influence suitability.",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("AI Sentiment Scraper (Simulated)")
    transcript = st.sidebar.text_area(
        "City Council Transcript",
        height=160,
        key="transcript",
        placeholder="Paste an excerpt from a council or planning commission meeting here...",
    )

    if st.sidebar.button("Run AI Sentiment Scraper"):
        sentiment_score = simulate_sentiment_score(transcript)
        # Map 0–100 sentiment to a 0–10 weight suggestion, but also
        # store the 0–100 as a separate value for transparency.
        suggested_weight = int(round(sentiment_score / 10))
        st.session_state["w_sentiment"] = suggested_weight
        st.session_state["last_scraped_sentiment"] = sentiment_score
        st.experimental_rerun()

    if "last_scraped_sentiment" in st.session_state:
        st.sidebar.caption(
            f"Last scraped council sentiment score: "
            f"**{st.session_state['last_scraped_sentiment']} / 100**"
        )

    return {
        "power": float(w_power),
        "fiber": float(w_fiber),
        "water": float(w_water),
        "highway": float(w_highway),
        "rail": float(w_rail),
        "solar": float(w_solar),
        "wind": float(w_wind),
        "flood_risk": float(w_flood_risk),
        "sentiment": float(w_sentiment),
    }


def render_map(global_scores: Dict[str, float]) -> None:
    # Centered roughly on the Twin Cities
    center_lat, center_lon = 44.9778, -93.2650
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=8,
        tiles="cartodbdark_matter",
    )

    for name, parcel in TAP_DATA.items():
        lat, lon = parcel["lat"], parcel["lon"]
        score = global_scores.get(name, 0.0)
        bucket = score_to_bucket(score)

        popup_html = f"""
        <div style="font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; font-size: 12px; color:#f9fafb; background:#020617;">
            <div style="font-weight:600; margin-bottom:4px;">{name}</div>
            <div style="margin-bottom:4px; color:#9ca3af;">{parcel['city']}</div>
            <div style="margin-bottom:4px;">
                <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#111827;border:1px solid #374151;">
                    Global Score: <span style="font-weight:600;">{score:.1f}</span> / 100
                </span>
            </div>
            <div style="color:#9ca3af;">Bucket: <strong>{bucket}</strong></div>
        </div>
        """
        color = (
            "lime"
            if bucket == "High"
            else "orange"
            if bucket == "Medium"
            else "red"
        )

        folium.CircleMarker(
            location=[lat, lon],
            radius=9,
            fill=True,
            fill_opacity=0.9,
            color=color,
            fill_color=color,
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(m)

    st_folium(m, width="100%", height=600)


def main() -> None:
    st.markdown(
        "<h2 style='color:#f9fafb; margin-bottom:0.25rem;'>Suitability Engine – Upper Midwest</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<span style='color:#9ca3af; font-size:0.9rem;'>Twin Cities‑anchored multi‑factor land screening for institutional infrastructure.</span>",
        unsafe_allow_html=True,
    )

    weights = render_sidebar()

    # Compute scores per parcel
    parcel_scores: Dict[str, float] = {}
    for name, parcel in TAP_DATA.items():
        score, _ = compute_parcel_score(
            parcel=parcel,
            weights=weights,
            flood_risk_slider=int(weights["flood_risk"]),
        )
        parcel_scores[name] = score

    # Layout: left metrics + table, right map
    col_left, col_right = st.columns([0.45, 0.55], gap="large")

    with col_left:
        st.subheader("Global Suitability Overview")

        # Sort parcels by score descending
        ranked = sorted(parcel_scores.items(), key=lambda x: x[1], reverse=True)
        if ranked:
            top_name, top_score = ranked[0]
        else:
            top_name, top_score = "—", 0.0

        m1, m2 = st.columns(2)
        with m1:
            st.metric("Top Parcel Score", f"{top_score:0.1f} / 100")
        with m2:
            st.metric("Top Parcel", top_name)

        st.markdown("### Parcels")
        for name, score in ranked:
            bucket = score_to_bucket(score)
            pill_class = bucket_to_class(score)
            city = TAP_DATA[name]["city"]
            st.markdown(
                f"""
                <div style="display:flex;justify-content:space-between;align-items:center;padding:0.35rem 0.5rem;border-bottom:1px solid #1f2937;">
                    <div>
                        <div class="parcel-header">{name}</div>
                        <div style="font-size:0.75rem;color:#9ca3af;">{city}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:0.9rem;font-weight:600;color:#e5e7eb;">{score:0.1f}</div>
                        <span class="suitability-pill {pill_class}">{bucket} Suitability</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_right:
        st.subheader("Spatial View")
        render_map(parcel_scores)


if __name__ == "__main__":
    main()

