"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
from utils.profile import load_profile, save_profile, update_preferences

# Wardrobe radio choices.
WARDROBE_EXAMPLE = "Example wardrobe"
WARDROBE_EMPTY = "Empty wardrobe (new user)"
WARDROBE_PROFILE = "My saved profile"


def _select_wardrobe(wardrobe_choice: str) -> dict:
    """Resolve the radio choice to an actual wardrobe dict."""
    if wardrobe_choice == WARDROBE_EXAMPLE:
        return get_example_wardrobe()
    if wardrobe_choice == WARDROBE_PROFILE:
        return load_profile()["wardrobe"]
    return get_empty_wardrobe()


# ── query handler ─────────────────────────────────────────────────────────────

def _format_listing(item: dict) -> str:
    """Format a listing dict into a readable block for the 'Top listing' panel."""
    lines = [
        item["title"],
        f"${item['price']:g} · {item['platform']}",
        f"Size {item['size']} · {item['condition']}",
        "Style: " + ", ".join(item["style_tags"]),
    ]
    if item.get("brand"):
        lines.append(f"Brand: {item['brand']}")
    lines.append("")  # blank line before the description
    lines.append(item["description"])
    return "\n".join(lines)


def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Returns five strings mapped to the output panels:
        (listing_text, outfit_suggestion, fit_card, price_check, trends)
    The listing panel is prefixed with a retry notice when refine_search had to
    loosen constraints. On error, the message goes in panel 1 and the rest blank.
    """
    # 1. Guard against an empty query.
    if not user_query or not user_query.strip():
        return "Please enter what you're looking for.", "", "", "", ""

    # 2. Select the wardrobe based on the radio choice.
    wardrobe = _select_wardrobe(wardrobe_choice)

    # 3. Run the agent.
    session = run_agent(user_query, wardrobe)

    # 4. On error, show the message in the first panel only.
    if session["error"]:
        return session["error"], "", "", "", ""

    # 5. If this is the saved profile, remember the refined preferences (stretch C).
    if wardrobe_choice == WARDROBE_PROFILE:
        profile = load_profile()
        update_preferences(profile, session["parsed"])
        save_profile(profile)

    # 6. Format the results for the five panels.
    listing_text = _format_listing(session["selected_item"])
    if session["notice"]:
        listing_text = f"⚠️ {session['notice']}\n\n{listing_text}"
    return (
        listing_text,
        session["outfit_suggestion"],
        session["fit_card"],
        session["price_check"] or "",
        session["trends"] or "",
    )


def save_wardrobe_to_profile(wardrobe_choice: str) -> str:
    """Persist the currently-selected wardrobe as the user's saved profile."""
    wardrobe = _select_wardrobe(wardrobe_choice)
    profile = load_profile()
    profile["wardrobe"] = wardrobe
    save_profile(profile)
    count = len(wardrobe.get("items", []))
    return f"✅ Saved {count} item(s) to your profile — pick “{WARDROBE_PROFILE}” to reuse them."


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=[WARDROBE_EXAMPLE, WARDROBE_EMPTY, WARDROBE_PROFILE],
                value=WARDROBE_EXAMPLE,
                label="Wardrobe",
                scale=1,
            )

        with gr.Row():
            submit_btn = gr.Button("Find it", variant="primary", scale=3)
            save_btn = gr.Button("💾 Save wardrobe to my profile", scale=1)
        profile_status = gr.Markdown("")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        with gr.Row():
            price_output = gr.Textbox(
                label="💰 Price check",
                lines=3,
                interactive=False,
            )
            trends_output = gr.Textbox(
                label="🔥 Trending in your size",
                lines=3,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        outputs = [listing_output, outfit_output, fitcard_output, price_output, trends_output]
        submit_btn.click(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)
        query_input.submit(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)
        save_btn.click(fn=save_wardrobe_to_profile, inputs=[wardrobe_choice], outputs=[profile_status])

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
