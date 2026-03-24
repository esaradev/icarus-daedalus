# SKILL — World Labs Marble API

## Overview

This skill enables Icarus to generate 3D worlds using the World Labs Marble API. Each world is a navigable 3D scene that can be explored in a browser.

## API Details

- **Model:** `marble-0.1-mini`
- **Cost:** ~$0.18 per world generation
- **Output:** A shareable URL to a navigable 3D world

## API Usage

### Generate a World

```
POST https://api.worldlabs.ai/v1/generations
Content-Type: application/json
Authorization: Bearer $WORLD_LABS_API_KEY

{
  "model": "marble-0.1-mini",
  "prompt": "<scene description>",
  "settings": {
    "quality": "standard"
  }
}
```

### Check Generation Status

```
GET https://api.worldlabs.ai/v1/generations/{generation_id}
Authorization: Bearer $WORLD_LABS_API_KEY
```

### Response Format

```json
{
  "id": "gen_...",
  "status": "completed",
  "url": "https://worldlabs.ai/world/...",
  "created_at": "2026-03-19T00:00:00Z"
}
```

## Prompting Guidelines

### What Works Well

- Specific architectural descriptions with materials and lighting
- Mood and atmosphere keywords (e.g., "overcast", "golden hour", "misty")
- Clear spatial relationships ("a narrow alley opening into a wide plaza")
- Cultural and historical references for architectural style

### Prompt Structure

A good Marble prompt includes:

1. **Setting** — Where is this? (abandoned cathedral, mountain village, underwater station)
2. **Architecture** — What structures exist? Be specific about materials, scale, condition.
3. **Lighting** — Time of day, weather, light sources, shadows.
4. **Atmosphere** — Mood, temperature feeling, sounds implied by the space.
5. **Details** — Small elements that make it real (moss on stone, rust on metal, light through stained glass).

### Example Prompt

> A narrow medieval alley in a coastal town at dusk. Limestone walls stained with salt spray, wooden shutters half-open. Warm light spills from a doorway onto wet cobblestones. A stone archway frames a view of the harbor beyond, masts visible against a purple-grey sky. Hanging laundry stretches between buildings overhead. The air feels heavy with coming rain.

## Constraints

- Prompts should be 50-200 words for best results
- Avoid prompting for people or characters (Marble focuses on environments)
- Avoid text or signage in scenes (tends to render poorly)
- One coherent scene per generation — don't describe multiple disconnected spaces
