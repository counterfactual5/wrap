"""Caption clause timing built from TTS sentence boundaries.

- clauses_from_boundaries: Frame-accurate caption items from TTS sentence boundaries and total duration
"""
import re

def _split_sentence_clauses(sentence, max_chars=20):
    """Split a long Chinese/English sentence into readable subtitle clauses (8..22 chars)."""
    s = sentence.strip()
    if not s:
        return []
    if len(s) <= max_chars:
        return [s]
    # Split on secondary punctuation while preserving delimiters
    parts = re.split(r"([，、；：,;:])", s)
    raw_clauses = []
    cur = ""
    for p in parts:
        if not p:
            continue
        if p in "，、；：,;:":
            cur += p
            raw_clauses.append(cur.strip())
            cur = ""
        else:
            cur += p
    if cur.strip():
        raw_clauses.append(cur.strip())

    # Merge tiny fragments (< 7 chars) into adjacent clauses so captions don't flicker
    merged = []
    buf = ""
    for cl in raw_clauses:
        if not buf:
            buf = cl
        elif len(re.sub(r"\W+", "", buf)) < 7 or len(buf) + len(cl) <= max_chars:
            buf += cl
        else:
            merged.append(buf)
            buf = cl
    if buf:
        if merged and len(re.sub(r"\W+", "", buf)) < 6 and len(merged[-1]) + len(buf) <= max_chars + 6:
            merged[-1] += buf
        else:
            merged.append(buf)
    return merged


def clauses_from_boundaries(text, boundaries, total_duration, fps=30, max_chars=20):
    """Build frame-accurate caption items from TTS sentence boundaries and total duration."""
    text = (text or "").strip()
    if not text:
        return []

    sent_Bounds = [b for b in (boundaries or []) if b.get("type") == "SentenceBoundary" and b.get("text")]
    if not sent_Bounds:
        # Fallback: split full text into major sentences first
        raw_sents = [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if s.strip()]
        if not raw_sents:
            raw_sents = [text]
        total_chars = max(1, sum(len(s) for s in raw_sents))
        cursor = 0.05
        avail = max(0.5, total_duration - 0.15)
        sent_Bounds = []
        for s in raw_sents:
            dur = avail * (len(s) / total_chars)
            sent_Bounds.append({"offset_sec": cursor, "duration_sec": dur, "text": s})
            cursor += dur

    items = []
    prev_frame = -1
    for sb in sent_Bounds:
        s_text = sb["text"].strip()
        s_off = max(0.0, float(sb.get("offset_sec", 0.0)))
        s_dur = max(0.2, float(sb.get("duration_sec", 1.0)))
        clauses = _split_sentence_clauses(s_text, max_chars=max_chars)
        if not clauses:
            continue
        char_weights = [max(1, len(re.sub(r"\W+", "", c))) for c in clauses]
        total_w = sum(char_weights)
        c_cursor = s_off
        for c_text, w in zip(clauses, char_weights):
            c_dur = s_dur * (w / total_w)
            f_start = int(round(c_cursor * fps))
            if not items and f_start <= 4:
                f_start = 0
            if f_start <= prev_frame:
                f_start = prev_frame + 1
            prev_frame = f_start
            f_end = max(f_start + 1, int(round((c_cursor + c_dur) * fps)))
            items.append({
                "frame": f_start,
                "end_frame": f_end,
                "text": c_text,
            })
            c_cursor += c_dur
    return items
