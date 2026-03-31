"""Tool handlers — the code that runs when the LLM calls each tool."""

import json
from . import state


def _json(payload) -> str:
    return json.dumps(payload, default=str)


def fabric_recall(args: dict, **kwargs) -> str:
    query = args.get("query", "").strip()
    if not query:
        return _json({"error": "No query provided"})
    try:
        results = state.recall(
            query,
            max_results=args.get("max_results", 5),
            agent=args.get("agent"),
            project=args.get("project"),
        )
        return _json({"query": query, "count": len(results), "entries": results})
    except Exception as e:
        return _json({"error": str(e)})


def fabric_write(args: dict, **kwargs) -> str:
    entry_type = args.get("type", "").strip()
    content = args.get("content", "").strip()
    summary = args.get("summary", "").strip()
    status = args.get("status", "").strip()
    assigned_to = args.get("assigned_to", "").strip()
    review_of = args.get("review_of", "").strip()
    revises = args.get("revises", "").strip()
    if not entry_type or not content or not summary:
        return _json({"error": "Need type, content, and summary"})
    if status == "open" and not assigned_to:
        return _json({"error": "status='open' requires assigned_to"})
    if entry_type == "review" and not review_of:
        return _json({"error": "type='review' requires review_of (agent:id of the entry you are reviewing)"})
    if review_of:
        parts = review_of.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1] or len(parts[1]) < 4:
            return _json({"error": f"review_of must be agent:id (e.g. icarus:a3f29b01), got '{review_of}'"})
        if not state.has_entry_ref(review_of):
            return _json({"error": f"review_of points to a missing entry: '{review_of}'"})
    if revises:
        parts = revises.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1] or len(parts[1]) < 4:
            return _json({"error": f"revises must be agent:id (e.g. icarus:a3f29b01), got '{revises}'"})
        if not state.has_entry_ref(revises):
            return _json({"error": f"revises points to a missing entry: '{revises}'"})
    tv = args.get("training_value", "").strip()
    if tv and tv not in ("high", "normal", "low"):
        return _json({"error": f"training_value must be high/normal/low, got '{tv}'"})
    try:
        path = state.write_entry(
            entry_type=entry_type,
            content=content,
            summary=summary,
            tags=args.get("tags", ""),
            status=status,
            outcome=args.get("outcome", ""),
            review_of=review_of,
            revises=revises,
            customer_id=args.get("customer_id", ""),
            assigned_to=assigned_to,
            training_value=tv,
            verified=args.get("verified", ""),
            evidence=args.get("evidence", ""),
            source_tool=args.get("source_tool", ""),
            artifact_paths=args.get("artifact_paths", ""),
        )
        # log usage telemetry when referencing other entries
        if review_of:
            ref_id = review_of.split(":", 1)[1] if ":" in review_of else review_of
            if state.was_recalled(ref_id):
                state.log_usage(ref_id, action="reviewed")
        if revises:
            ref_id = revises.split(":", 1)[1] if ":" in revises else revises
            if state.was_recalled(ref_id):
                state.log_usage(ref_id, action="revised")
        return _json({"status": "written", "path": path})
    except Exception as e:
        return _json({"error": str(e)})


def fabric_search(args: dict, **kwargs) -> str:
    query = args.get("query", "").strip()
    if not query:
        return _json({"error": "No query provided"})
    try:
        results = state.search_entries(query)
        return _json({"query": query, "count": len(results), "results": results})
    except Exception as e:
        return _json({"error": str(e)})


def fabric_pending(args: dict, **kwargs) -> str:
    try:
        open_tasks, reviews, open_tickets = state.read_pending(
            customer_id=args.get("customer_id"),
        )
        return _json({
            "open_tasks": open_tasks,
            "reviews_of_my_work": reviews,
            "open_tickets": open_tickets,
            "total": len(open_tasks) + len(reviews) + len(open_tickets),
        })
    except Exception as e:
        return _json({"error": str(e)})


def fabric_curate(args: dict, **kwargs) -> str:
    entry_id = args.get("entry_id", "").strip()
    training_value = args.get("training_value", "").strip()
    if not entry_id or training_value not in ("high", "normal", "low"):
        return _json({"error": "Need entry_id and training_value (high/normal/low)"})
    try:
        result = state.curate_entry(entry_id, training_value)
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_export(args: dict, **kwargs) -> str:
    try:
        result = state.export_training(mode=args.get("mode", "normal"))
        result.pop("_training_data", None)
        result.pop("training_data_path", None)
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_train(args: dict, **kwargs) -> str:
    try:
        result = state.start_training(
            model=args.get("model"),
            suffix=args.get("suffix"),
            epochs=args.get("epochs", 3),
            batch_size=args.get("batch_size"),
            learning_rate=args.get("learning_rate"),
            checkpoints=args.get("n_checkpoints"),
        )
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_train_status(args: dict, **kwargs) -> str:
    try:
        result = state.check_training(job_id=args.get("job_id"))
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_models(args: dict, **kwargs) -> str:
    try:
        registry = state.list_models()
        return _json(registry)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_eval(args: dict, **kwargs) -> str:
    candidate = args.get("candidate_model", "").strip()
    if not candidate:
        return _json({"error": "candidate_model is required"})
    try:
        result = state.run_eval(
            candidate_model=candidate,
            base_model=args.get("base_model"),
            sample_count=args.get("sample_count", 10),
        )
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_switch_model(args: dict, **kwargs) -> str:
    model_id = args.get("model_id", "").strip()
    if not model_id:
        return _json({"error": "model_id is required"})
    try:
        result = state.switch_model(
            model_id=model_id,
            min_eval_score=args.get("min_eval_score", 0.7),
        )
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_rollback_model(args: dict, **kwargs) -> str:
    try:
        result = state.rollback_model()
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_brief(args: dict, **kwargs) -> str:
    try:
        result = state.build_brief()
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_telemetry(args: dict, **kwargs) -> str:
    try:
        result = state.get_telemetry(last_n=args.get("last_n", 50))
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})
