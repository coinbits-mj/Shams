# QCC Business Overview
*Knowledge Base Document for Shams — Synthesized March 2026*

---

## THE BUSINESS AT A GLANCE

**Queen City Coffee Roasters (QCC)** is a specialty coffee platform founded and operated by Maher Janajri. It is not just a café company — it is the seed of a $100M+ infrastructure platform designed to dominate specialty coffee in the Northeast and eventually beyond.

**Current footprint:**
- **Plainfield, NJ** — flagship retail café location
- **Clifton, NJ** — second retail café, approximately 4–5 months old, already generating ~$70K/month with strong margins
- **10,000 sq ft roasting facility** — wholesale roasting operations; the core of the scalable business
- **Two co-owners/operators:** Maher Janajri and Monica Janajri

**Key team members:**
- Brandon Perez — shift lead, Plainfield (role currently being restructured — see Active Deals doc)
- Maryam Muhammad — shift lead, Plainfield
- Belal Lulu — shift lead, Clifton

**Tech stack:** Square (POS), MarginEdge (food costing), Mercury (banking), Klaviyo (email), Recharge (subscriptions), ShipStation, Slack (internal comms), Railway (infrastructure hosting)

---

## FINANCIAL PROFILE

- **Clifton location:** ~$70K/month gross revenue, ~4–5 months old, strong margins post one-time normalization. Three untapped revenue streams (delivery, evening concept, catering) expected to push toward $100K/month target at very high incremental margins
- **Net margins:** ~30% blended across operations at normalized run rate
- **Roasting capacity:** 10,000 sq ft facility — wholesale can scale significantly without proportional headcount
- **Wholesale mix:** Current wholesale operations are a growing share of revenue; the long-term vision is to flip the ratio from retail-dominant to wholesale-dominant (modeled after Red House Roasters' 75% wholesale mix)

---

## RUMI — THE OPERATING SYSTEM

Rumi is QCC's internal AI-powered Mission Control platform. It is one of the most important assets in the business and one of the most underappreciated externally.

**What Rumi does today:**
- P&L reporting integrating Square, Mercury, and MarginEdge data
- Slack bot with 8+ features: Google Reviews alerts, shift summaries, weather alerts, weekly digests, inventory alerts, and more
- Customer acquisition infrastructure: zip-code landing pages, Square promo automation, SMS retention loops
- Growth Engine module (recently built) with structured Slack output formats
- CBDT (Competency-Based Development & Training) module for staff training across both locations, with location-aware scoping (Plainfield vs Clifton), quiz-based assessments, and manager sign-off flows
- UberEats integration work underway

**What Rumi will become:**
- The operating OS for every QCC location (retail + wholesale + roastery)
- The platform that compresses time-to-profitability on new location acquisitions
- A SaaS product licensed to other multi-location coffee operators ($500–2K/month per location = $10M+ ARR potential)
- The backbone of the Eversys pay-per-shot model (remote dialing, usage billing, inventory replenishment)
- Potentially white-labeled for larger chains

**Technical details:**
- Built in Python, hosted on Railway
- Posts to Slack
- Git repo: `coffee-pl-bot` (located at `~/Downloads/coffee-pl-bot`)
- Integrations: Square API, MarginEdge API, Mercury, Slack webhooks

**The Rumi insight that matters most to Shams:** Rumi is not a cost center. It is the flywheel. Without it, QCC is a good coffee company. With it fully built out, QCC is a defensible platform.

---

## THE PLATFORM VISION — WHAT QCC IS BECOMING

This is critical context. Maher is not building a café chain. He is building a **coffee infrastructure platform.** The components:

### 1. QCC Retail (Cash Flow Engine)
- Scale to 6–8 locations in the Northeast
- Each location: $70–100K/month, 30% net margins
- Rumi compresses operational complexity — no "unicorn manager" required

### 2. QCC Wholesale (Highest-Margin Lever)
- Target: hotels, offices, universities, restaurants, catering
- 10,000 sq ft facility has untapped capacity
- Goal: $500K–$1M/month wholesale within 3 years
- Red House Roasters acquisition (75% wholesale) would turbocharge this immediately

### 3. Eversys Pay-Per-Shot ("Brew by Queen City")
- Model: Client gets machine for free + installation fee → pays monthly based on shot usage with minimums
- QCC owns the machine, supplies the coffee, manages everything remotely via Rumi
- Shot pricing: $0.80–$1.50/shot variable on volume
- Per-machine economics: $2,250–$7,200/month depending on use case
- At 100 machines: $250K–$600K/month
- Target first accounts: premium hotels, corporate campuses, high-end gyms, universities, upscale restaurants
- Machine consideration: Eversys (preferred, open API, specialty credibility) but lead time 3–6 months; Schaerer and Franke as bridge options; segmented fleet by account size
- **Rumi is the backbone** — remote dialing, telemetry, usage billing, inventory triggers

### 4. Grind Capital (Equipment Leasing)
- Lease espresso equipment (La Marzocco, Mazzer, Mahlkönig) at MAP pricing
- QCC gets 30% below retail via distributor relationships
- Bundle with maintenance contracts and tied coffee supply agreements
- The moat: Rumi diagnostics + remote support = managed service, not just leasing

### 5. Green Coffee Importing & Trading
- QCC already buys green; cutting out the importer adds 20–40% margin
- Direct trade relationships: Ethiopia, Colombia, Yemen
- Long-term: become a green coffee supplier to other roasters
- $10M+ business on its own with the right sourcing relationships

### 6. E-Commerce & DTC
- Recharge subscriptions (already live)
- AI-driven coffee taste profiling quiz — dual purpose: top-of-funnel conversion + demand intelligence feeding roastery sourcing decisions
- Conservative $30K/month by month 12, base case $50K, upside $80–100K with subscription optimization
- Klaviyo email flows, in-café QR activation, community channel distribution

### 7. Zenbumi Distribution (Multi-Brand Distributor Play)
- If the matcha deal works, QCC becomes a multi-brand NJ distributor
- Add 2–3 complementary beverage brands to leverage existing wholesale relationships
- See Active Deals doc for negotiation status

### 8. Rumi SaaS (Separate Revenue Stream)
- License to other specialty coffee operators once proven at QCC
- Target: $500–2K/month per location, multi-location groups
- White-label option for chains
- $10M+ ARR potential

### 9. Halal Finance Layer (The Exponential Mechanic)
- Lightning Network payments integrated into Rumi → displaces Square/Toast fees
- Musharaka-structured working capital for F&B operators (risk-sharing, repaid through transaction flow, explicitly no riba)
- Coinbits providing Bitcoin treasury infrastructure for operators
- The combined vision: "Square + Shopify + Coinbase + halal finance" for Muslim-owned and halal-aligned F&B businesses
- This market has no existing solution. QCC/Rumi is a proof of concept for the platform.

---

## THREE-YEAR REVENUE MAP

| Stream | 3-Year Monthly Target |
|---|---|
| Retail (6–8 locations) | $600–800K |
| Wholesale | $1–1.5M |
| Equipment leasing + tied coffee | $500K–1M |
| Green coffee / importing | $500K–1M |
| E-commerce / DTC | $200–400K |
| Distribution (multi-brand) | $300–500K |
| White label / private label | $200–400K |
| Rumi SaaS | $100–300K |
| **Total gross** | **$3.4–5.9M/month** |

Net at 20–25% blended = $680K–$1.5M/month.

---

## CUSTOMER ACQUISITION INFRASTRUCTURE

- **The "last mile advertising gap":** National coffee brands can't efficiently compete for hyper-local geographic search intent — local paid search is underpriced and underutilized by local operators. QCC is building to exploit this.
- **System:** Zip-code-specific landing pages → single phone number capture → Rumi automation (Square promo creation + Slack staff briefing before customer arrives) → SMS retention loop
- **Four-daypart customer segmentation:** Commuter, WFH/brunch, afternoon, evening — each with distinct messaging and offers
- **Target LTV:** $2,200 per customer
- **Critical habit window:** 3–5 visits in the first 2–3 weeks

---

## MAHER'S OPERATING PHILOSOPHY

- **Systems over heroics:** QCC does not need unicorn managers. It needs Rumi.
- **Wholesale > retail:** The long-term margin and scale advantage is clear.
- **Halal is a floor, not a ceiling:** Not just compliance — exemplary structure.
- **Bitcoin treasury:** Sound money principles applied to business cash management.
- **Community as flywheel:** Capital deployed to community returns as loyalty, talent, and barakah.
- **Idris:** Everything being built should be something his son can inherit and build upon.
