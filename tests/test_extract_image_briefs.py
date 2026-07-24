"""
Coverage for assets_library/extract_image_briefs.py: pulls just the
image-generation fields out of a MKT-LI1 batch response, skipping any
post with no image_description (carousels, or a text_post the model
didn't draft one for) without erroring.
"""
from assets_library.extract_image_briefs import extract_image_briefs


def _post(**overrides):
    base = {
        "id": "queue-1", "topic": "Kubernetes cert path", "pillar_name": "Cloud and AI Execution",
        "format": "text_post", "image_description": "Single standalone diagram...",
    }
    base.update(overrides)
    return base


def test_extracts_topic_pillar_description_and_queue_id():
    batch = {"posts": [_post()]}
    briefs = extract_image_briefs(batch)
    assert briefs == [{
        "post_topic": "Kubernetes cert path",
        "pillar": "Cloud and AI Execution",
        "image_description": "Single standalone diagram...",
        "queue_id": "queue-1",
    }]


def test_skips_posts_with_no_image_description_without_erroring():
    batch = {"posts": [_post(image_description=None, format="document_carousel"), _post()]}
    briefs = extract_image_briefs(batch)
    assert len(briefs) == 1
    assert briefs[0]["post_topic"] == "Kubernetes cert path"


def test_accepts_a_bare_list_not_just_a_posts_wrapped_dict():
    briefs = extract_image_briefs([_post()])
    assert len(briefs) == 1


def test_empty_batch_returns_empty_list():
    assert extract_image_briefs({"posts": []}) == []


def test_missing_queue_id_does_not_error():
    batch = {"posts": [_post(id=None)]}
    briefs = extract_image_briefs(batch)
    assert briefs[0]["queue_id"] is None
