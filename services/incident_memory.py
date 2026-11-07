from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def incident_text(incident):
    pm = incident.postmortem
    return " ".join(filter(None, [incident.title, incident.service, incident.category, incident.summary, incident.symptoms, incident.evidence[:2500], pm.confirmed_root_cause if pm else "", pm.actual_resolution if pm else "", pm.lessons_learned if pm else ""]))


def retrieve_similar(query, candidates, limit=3):
    """Return resolved incidents with verified postmortems, ranked by TF-IDF cosine."""
    candidates = [i for i in candidates if i.status == "Resolved" and i.postmortem]
    if not candidates:
        return []
    corpus = [query] + [incident_text(i) for i in candidates]
    matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True).fit_transform(corpus)
    scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    return [{"incident": incident, "score": float(score)} for incident, score in ranked[:limit] if score > 0]
