# Titan-only facts for blog briefs

**Owner: Albert.** This file is the only source a brief may quote for prices, policies
and local claims (decision Q8, 2026-10-07: "a published price is a promise, so a number
you edited is a decision"). Product names and specs come read-only from the Airtable
Master Flooring Catalogue; nothing numeric about price is ever computed from the
catalogue for a post. A brief that needs a fact this file does not hold is flagged
`titan_facts_missing` and the writer leaves the sentence out rather than guessing.

Every line below is either filled by Albert or marked `TODO`. The engine treats a
`TODO` as absent.

## Pricing ranges (CAD, material only, per sq ft, before tax)

| Material | Entry | Mid | Premium | Notes |
|---|---|---|---|---|
| Luxury vinyl plank (SPC / WPC) | TODO | TODO | TODO | |
| Laminate | TODO | TODO | TODO | |
| Engineered hardwood | TODO | TODO | TODO | |
| Solid hardwood | TODO | TODO | TODO | |
| Tile | TODO | TODO | TODO | |

## Installation ranges (CAD per sq ft, labour only)

| Job | Range | Notes |
|---|---|---|
| Click-lock vinyl / laminate | TODO | |
| Glue-down vinyl | TODO | |
| Engineered hardwood (nail / glue / float) | TODO | |
| Solid hardwood | TODO | |
| Stair refinishing / recap | TODO | per stair |
| Subfloor prep / levelling | TODO | |
| Removal and disposal of old flooring | TODO | |

## Ontario / GTA facts the writer may use

- Showroom: 1060 Britannia Rd East #2, Mississauga, ON L4W 4T1. Serving the GTA since 2012.
- Basements: TODO (moisture testing practice, vapour barrier / underlayment Titan specifies, what Titan refuses to install below grade).
- Humidity and seasonal movement: TODO (acclimation days Titan requires, RH range).
- Permits / condo rules: TODO.
- Warranty: TODO (what Titan's install warranty covers, in plain words).

## Titan products and services the writer may name

- Product families: Solid Hardwood, Engineered Hardwood, Laminate, Vinyl (from `titan-website/lib/site.ts`).
- Services: Flooring Installation, Stair Refinishing.
- Brands / lines Titan stocks: read from the Airtable catalogue at brief time (names only).

## Things the writer must never claim

- A price not in this file.
- A competitor comparison by name.
- That any product is "100% waterproof" (use "waterproof-rated" / "water-resistant" per the spec).
- TODO (add Albert's own no-gos).

## Log

- 2026-10-07 — created as a skeleton in Phase 0 of the content engine; Albert to fill.
