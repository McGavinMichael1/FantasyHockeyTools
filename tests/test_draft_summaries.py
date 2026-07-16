from types import SimpleNamespace

from scripts import build_draft_summaries as summaries


def _text(s):
    return SimpleNamespace(type='text', text=s)


def _tool(kind):
    return SimpleNamespace(type=kind)


# With server-side web search, resp.content interleaves the model's pre-search
# narration with the real answer. Joining every text block stapled them
# together -- 16 of 18 API-produced entries in the 2026-07-15 cache opened
# with "I'll search for <player>'s current situation...".
def test_summary_text_excludes_narration_from_before_the_search():
    content = [
        _text("I'll search for Nick Suzuki's current situation ahead of the "
              '2026-27 season.'),
        _tool('server_tool_use'),
        _tool('web_search_tool_result'),
        _text("Suzuki is locked in as Montreal's clear No. 1 center."),
    ]

    assert summaries._final_text(content) == (
        "Suzuki is locked in as Montreal's clear No. 1 center.")


def test_summary_text_keeps_everything_when_no_search_ran():
    content = [_text("Boldy remains locked onto Minnesota's top line.")]

    assert summaries._final_text(content) == (
        "Boldy remains locked onto Minnesota's top line.")


def test_summary_text_joins_an_answer_split_across_blocks_after_the_search():
    content = [
        _text("I'll research this player."),
        _tool('server_tool_use'),
        _tool('web_search_tool_result'),
        _text('First sentence.'),
        _text(' Second sentence.'),
    ]

    assert summaries._final_text(content) == 'First sentence. Second sentence.'


def test_rejects_search_limit_fallback_as_a_summary():
    fallback = (
        "I wasn't able to complete this request reliably: my web-search tool "
        "hit a hard usage limit before I could capture any readable results."
    )

    assert summaries._is_usable_summary(fallback) is False


# The three fallbacks below are verbatim from entries that reached
# draft_summaries.json on 2026-07-15: the same failure, worded three ways.
# Matching one transcript's phrasing is what let two of them through.
def test_rejects_search_limit_fallback_phrased_as_web_research():
    fallback = (
        "I'll search for Jason Robertson's current situation heading into the "
        "2026-27 season.I was unable to complete the web research for this - "
        "the search tool hit its usage limit for this session and returned no "
        "results across repeated attempts, so I cannot verify Jason "
        "Robertson's current 2026-27 situation."
    )

    assert summaries._is_usable_summary(fallback) is False


def test_rejects_search_limit_fallback_phrased_as_limit_exceeded():
    fallback = (
        "I'll search for William Nylander's current situation heading into the "
        "2026-27 season.I was unable to complete live web searches - the "
        "search tool's usage limit was exceeded before any results could be "
        "retrieved, so I can't confirm the very latest July 2026 news."
    )

    assert summaries._is_usable_summary(fallback) is False


def test_accepts_a_real_summary_that_describes_a_player_failing_to_finish():
    """'unable to complete' is ordinary hockey prose -- rejecting on the
    phrase alone would discard good summaries about injured players."""
    real = (
        "Forsberg was unable to complete last season after a lower-body injury "
        "in March, but he is fully cleared for camp and returns to Nashville's "
        "top line. His PP1 role is unchanged, which supports the model's "
        "projection. Draft him at his ADP."
    )

    assert summaries._is_usable_summary(real) is True


def test_top_50_players_receive_the_deeper_search_budget():
    assert summaries._search_budget(49) == 5
    assert summaries._search_budget(50) == 3


def test_all_summary_calls_allow_the_larger_token_budget():
    assert summaries.MAX_TOKENS == 4096
