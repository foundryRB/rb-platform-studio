---
title: Visual identity
id: DOC-REF-BRAND-001
type: Reference
status: Active
updated: "2026-09-13"
description: The RB Software Engineering identity and the application-owned styling sources.
---

Platform Studio wears the RB Software Engineering identity: the lockup (the RB tile, "Software Engineering" over "RB") in the header, the brand's green as the primary and the ambient field's colour, neutral greys around it, system fonts for text and JetBrains Mono for the lockup's second line.

## Application sources

| Surface | Source |
| --- | --- |
| Palette, spacing and ambient motion | `studio-frontend/src/index.css` |
| Application header and navigation | `studio-frontend/src/views/templates/MainLayout.tsx` |
| Decorative contours and particles | `studio-frontend/src/views/atoms/AmbientField.tsx` |
| Header lockup | `studio-frontend/src/components/Lockup.tsx` |
| Typography utility mapping | `studio-frontend/tailwind.config.js` |
| Browser mark | `studio-frontend/public/logo-mark.svg` |

Dark is the default; the existing Light/Dark preference persists across visits. Both appearances carry continuous side fields and sparse rising, fading particles. Hidden pages pause the decoration; reduced-motion preferences stop it. Printing hides the atmosphere and navigation.

The header and working area share a 1120px frame with responsive gutters. Cards, tables and forms use opaque reading surfaces. The navigation uses a restrained translucent background. Material and motion are authored application choices.

Brand changes belong in these application-owned files. Generated platform manifests, deployment values and conformance results preserve their domain formats.
