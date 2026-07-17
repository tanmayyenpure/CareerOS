"""
YouTube Data API v3 helper.

Why this file exists: Gemini (or any LLM) will happily invent a
resource_url that looks like a real YouTube link but 404s. Instead of
asking the AI for a URL, we ask it for `search_keywords` and look up a
REAL, currently-live video ourselves.

Setup:
  1. Enable "YouTube Data API v3" on a Google Cloud project:
     https://console.cloud.google.com/apis/library/youtube.googleapis.com
  2. Create an API key: https://console.cloud.google.com/apis/credentials
  3. Add to .env:  YOUTUBE_API_KEY=your-key-here
  4. pip install requests --break-system-packages   (if not already installed)

Free quota: 10,000 units/day. A search.list call costs 100 units, so
~100 lookups/day on the free tier. If a request has 8 milestones, that's
8 lookups per roadmap generation -> ~12 roadmaps/day before you hit quota.
If you outgrow that, add a simple cache keyed on the search query (e.g. a
`video_cache` table or Redis) before calling search_youtube_video().

Everything here fails soft: if the key is missing, the quota is used up,
or the network call errors out, we fall back to a YouTube *search results*
link (always real, never 404s) instead of raising and breaking roadmap
generation.
"""
import os
import re
import urllib.parse

import requests

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _parse_iso8601_duration(duration):
    """
    Converts YouTube's ISO 8601 duration (e.g. 'PT12M34S', 'PT1H2M3S') into
    a human-friendly 'H:MM:SS' or 'M:SS' string. Returns None if unparsable.
    """
    if not duration:
        return None
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    minutes += 0
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_view_count(view_count):
    """Converts a raw view count string/int into a compact '1.2M views' style string."""
    if view_count is None:
        return None
    try:
        n = int(view_count)
    except (TypeError, ValueError):
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M views"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K views"
    return f"{n} views"


def _fetch_video_details(video_id):
    """
    Follow-up call to videos.list for a single video id, to get duration,
    view count, and thumbnail — none of which search.list returns. Costs
    only 1 quota unit (vs 100 for the search itself), and draws from the
    general 10,000-unit pool rather than the separate ~100/day search
    bucket, so it doesn't meaningfully affect your search budget.
    Returns a dict or {} on any failure — never raises.
    """
    if not YOUTUBE_API_KEY or not video_id:
        return {}

    params = {
        "part": "contentDetails,statistics,snippet",
        "id": video_id,
        "key": YOUTUBE_API_KEY,
    }
    try:
        resp = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=6)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}
        item = items[0]
        thumbnails = item.get("snippet", {}).get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("medium", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )
        return {
            "duration": _parse_iso8601_duration(item.get("contentDetails", {}).get("duration")),
            "views": _format_view_count(item.get("statistics", {}).get("viewCount")),
            "thumbnail": thumbnail_url,
        }
    except Exception as e:
        print(f"YouTube video details lookup failed for {video_id!r}: {e}")
        return {}


def search_youtube_video(query, max_results=1):
    """
    Returns the top matching YouTube video for `query` as:
        {"title": str, "channel": str, "url": str, "video_id": str,
         "duration": str|None, "views": str|None, "thumbnail": str|None}
    or None if no key is configured, the request fails, or nothing is found.
    Never raises.
    """
    if not YOUTUBE_API_KEY or not query:
        return None

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": "relevance",
        "safeSearch": "strict",
        "key": YOUTUBE_API_KEY,
    }

    try:
        resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=6)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None

        item = items[0]
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]

        result = {
            "title": snippet.get("title", "").strip(),
            "channel": snippet.get("channelTitle", "").strip(),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "video_id": video_id,
            "duration": None,
            "views": None,
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
        }

        # Cheap follow-up call for duration/views/better thumbnail. Fails
        # soft — if it errors, we still return the base result above.
        details = _fetch_video_details(video_id)
        result.update({k: v for k, v in details.items() if v})

        return result
    except Exception as e:
        print(f"YouTube search failed for query {query!r}: {e}")
        return None


def _fallback_search_link(query):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)


def enrich_with_video(item, keywords_field="search_keywords", title_field="title"):
    """
    Takes a dict (a milestone or a skill node) and mutates it in place,
    adding real video info:
        resource_url        -> a real, currently-live YouTube link
        resource_title       -> the actual video title
        resource_channel     -> the channel name (None if we only got the
                                 fallback search link)
        resource_video_id    -> the raw YouTube video id, used to build an
                                 embedded player (None on fallback)
        resource_duration    -> human-friendly duration e.g. "12:34" (or None)
        resource_views       -> compact view-count string e.g. "1.2M views" (or None)
        resource_thumbnail   -> thumbnail image URL (or None)

    Looks up `keywords_field` first (list or string); falls back to
    `title_field` if keywords aren't present. Never raises.
    """
    keywords = item.get(keywords_field)
    if keywords:
        query = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
    else:
        query = item.get(title_field, "")

    video = search_youtube_video(query) if query else None

    if video:
        item["resource_url"] = video["url"]
        item["resource_title"] = video["title"]
        item["resource_channel"] = video["channel"]
        item["resource_video_id"] = video.get("video_id")
        item["resource_duration"] = video.get("duration")
        item["resource_views"] = video.get("views")
        item["resource_thumbnail"] = video.get("thumbnail")
    else:
        item["resource_url"] = _fallback_search_link(query or item.get(title_field, ""))
        item["resource_title"] = "Search on YouTube"
        item["resource_channel"] = None
        item["resource_video_id"] = None
        item["resource_duration"] = None
        item["resource_views"] = None
        item["resource_thumbnail"] = None

    return item


def enrich_milestones_with_videos(milestones):
    """Convenience wrapper: enrich_with_video() over a list of milestones."""
    for m in milestones:
        enrich_with_video(m)
    return milestones