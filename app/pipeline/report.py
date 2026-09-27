from app.contracts.analysis import ExecutivePulseResult


def executive_markdown(project_title: str, result: ExecutivePulseResult) -> str:
    def bullets(values: list[str]) -> str:
        return (
            "\n".join(f"- {value}" for value in values)
            if values
            else "- None identified"
        )

    return f"""# Executive Pulse — {project_title}

## Campaign health

{result.campaign_health}

## Summary

{result.summary}

## What is working

{bullets(result.what_is_working)}

## What is not working

{bullets(result.what_is_not_working)}

## What changed

{bullets(result.what_changed)}

## Watch items

{bullets(result.watch_items)}

## Next actions

{bullets(result.next_actions)}
"""
