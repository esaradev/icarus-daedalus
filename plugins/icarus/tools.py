"""Tool handlers — the code that runs when the LLM calls each tool."""

import json
from . import state


def _json(payload) -> str:
    return json.dumps(payload, default=str)


def fabric_recall(args: dict, **kwargs) -> str:
    """Smart ranked retrieval from fabric."""
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
    """Write a new entry to fabric."""
    entry_type = args.get("type", "").strip()
    content = args.get("content", "").strip()
    summary = args.get("summary", "").strip()
    status = args.get("status", "").strip()
    assigned_to = args.get("assigned_to", "").strip()
    if not entry_type or not content or not summary:
        return _json({"error": "Need type, content, and summary"})
    if status == "open" and not assigned_to:
        return _json({"error": "Open handoffs require assigned_to"})
    try:
        path = state.write_entry(
            entry_type=entry_type,
            content=content,
            summary=summary,
            tags=args.get("tags", ""),
            status=status,
            outcome=args.get("outcome", ""),
            review_of=args.get("review_of", ""),
            revises=args.get("revises", ""),
            customer_id=args.get("customer_id", ""),
            assigned_to=assigned_to,
        )
        return _json({"status": "written", "path": path})
    except Exception as e:
        return _json({"error": str(e)})


def fabric_search(args: dict, **kwargs) -> str:
    """Keyword search across fabric entries."""
    query = args.get("query", "").strip()
    if not query:
        return _json({"error": "No query provided"})
    try:
        results = state.search_entries(query)
        return _json({"query": query, "count": len(results), "results": results})
    except Exception as e:
        return _json({"error": str(e)})


def fabric_pending(args: dict, **kwargs) -> str:
    """Show work waiting for this agent."""
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


def fabric_export(args: dict, **kwargs) -> str:
    """Export fabric entries as fine-tuning training pairs."""
    try:
        result = state.export_training()
        # don't send raw training data back to the LLM
        result.pop("_training_data", None)
        result.pop("training_data_path", None)
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def fabric_train(args: dict, **kwargs) -> str:
    """Start a Together AI fine-tune job."""
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
    """Check fine-tune job status."""
    try:
        result = state.check_training(job_id=args.get("job_id"))
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})
