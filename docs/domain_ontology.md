# Shared final GraphRAG entity ontology

**Status:** shared final ontology for both arms. This document records the domain rationale; it does not itself change workspace settings or create graph content. The shared entity list and both workspace settings currently match this ontology. Keep the entity list and extraction prompt identical across arms.

## Evidence and scope

The proposal is based on the 10-page Russian article by Spivakov, Orlov, and Ganoshenko, *Selection of a rational scheme of controlled rolling of plate with accelerated cooling on a reversing mill* ([`stat3.pdf`](../data/source/stat3.pdf#page=1)), and T. Tanaka's 28-page English review, *Controlled rolling of steel plate and strip* ([`tanaka1981.pdf`](../data/source/tanaka1981.pdf#page=1)). Page references below use **PDF page numbers**, with printed page numbers 260–269 for S (`stat3`) and 185–212 for T (Tanaka). Examples were checked against the PDF pages; MinerU text was used to locate passages. Treat OCR versions of symbols and equations as candidates to verify against the page image.

## Final type list

```yaml
entity_types:
  - PROCESS
  - PROCESS_ROUTE
  - PROCESS_STAGE
  - COOLING_METHOD
  - EQUIPMENT
  - STEEL_GRADE
  - ALLOY_FAMILY
  - PRODUCT_FORM
  - CHEMICAL_ELEMENT
  - PRECIPITATE
  - PHASE
  - MICROSTRUCTURE
  - PROPERTY
  - PROCESS_CONDITION
  - MODEL
  - FORMULA
```

These are **mutually distinguishable extraction targets**, not a license to turn every noun, number, table cell, or citation into a node. Keep page, document, original spelling, and any numeric value with its unit as provenance or attributes. A subtype can be represented by a relation without inventing a new entity type.

## Types, source examples, and traversal value

| Type | Boundary and PDF examples | Why a traversal needs it |
| --- | --- | --- |
| **PROCESS** | A metallurgical action or mechanism, not its schedule: controlled rolling / `контролируемая прокатка` in [S1](../data/source/stat3.pdf#page=1) and [T1](../data/source/tanaka1981.pdf#page=1); recrystallization in [S1](../data/source/stat3.pdf#page=1) and [T5–6](../data/source/tanaka1981.pdf#page=5); austenite-to-ferrite transformation in [T3–5](../data/source/tanaka1981.pdf#page=3). | Connects deformation and thermal operations to the phases, microstructures, and properties they change. Recrystallization is a process, not a phase or a stage label. |
| **PROCESS_ROUTE** | An ordered, named processing scheme: `КП+УО+КП` versus `КП+УО` in [S4–6](../data/source/stat3.pdf#page=4); the plate mill's “rough-hold-finish” schedule in [T21](../data/source/tanaka1981.pdf#page=21). | Lets a query compare alternative sequences and traverse each route's stages, cooling step, equipment, and outcomes. A route is more specific than generic controlled rolling. |
| **PROCESS_STAGE** | A bounded part of a route: roughing and finishing passes in [S3](../data/source/stat3.pdf#page=3); deformation in the recrystallization, non-recrystallization, and γ–α regions in [T1–2](../data/source/tanaka1981.pdf#page=1). | Preserves order and context: a finishing reduction or intermediate cooling step should not be attributed to the whole process indiscriminately. |
| **COOLING_METHOD** | A deliberate cooling mode: air holding/cooling and accelerated cooling (`УО`) in [S2–5](../data/source/stat3.pdf#page=2); controlled cooling in [T2](../data/source/tanaka1981.pdf#page=2), rapid run-out-table cooling and slow cooling after coiling in [T21](../data/source/tanaka1981.pdf#page=21), direct quenching in [T23](../data/source/tanaka1981.pdf#page=23). | Cooling is a central branch point between routes and resulting phases/properties. Keep a method distinct from a measured cooling rate (`PROCESS_CONDITION`). |
| **EQUIPMENT** | A physical mill or unit: reversing mill 3600, roughing/finishing stands, and the `УОВТ` cooling installation in [S2–5](../data/source/stat3.pdf#page=2); plate mill, hot-strip mill, and run-out table in [T20–21](../data/source/tanaka1981.pdf#page=20). | Links feasible routes and cooling methods to equipment constraints. Extract identifiable units or useful equipment classes, not every generic mention of a “mill.” |
| **STEEL_GRADE** | An explicit designation: `09Г2ФБ`, `10Г2ФБ`, `10Г2БТ` in [S1](../data/source/stat3.pdf#page=1); API `X70` strength grade in [T23](../data/source/tanaka1981.pdf#page=23). | Supports grade-specific paths through composition, route, product form, and measured properties. `К–56`/`К–60` in S1 are pipe strength classes; do not silently equate them with API X70. |
| **ALLOY_FAMILY** | A composition or metallurgical class broader than a grade: low-pearlite, low-alloy Nb-bearing steels in [S1](../data/source/stat3.pdf#page=1), [S5](../data/source/stat3.pdf#page=5); C–Mn–Nb and Nb-free/C–Mn steels in [T2](../data/source/tanaka1981.pdf#page=2), [T23](../data/source/tanaka1981.pdf#page=23). | Provides a cross-document bridge when grade designations differ but alloying patterns and mechanisms can be compared. Do not create a node for unqualified “steel.” |
| **PRODUCT_FORM** | The manufactured form or feedstock: continuously cast slab, thick plate, and linepipe in [S1](../data/source/stat3.pdf#page=1); plate versus hot-rolled strip and linepipe in [T1–2](../data/source/tanaka1981.pdf#page=1), [T21](../data/source/tanaka1981.pdf#page=21). | Prevents plate-mill schedules and strip-mill/coiling behavior from being conflated; connects feedstock to route and application. |
| **CHEMICAL_ELEMENT** | Explicit alloying/impurity elements: Nb and V in [S2](../data/source/stat3.pdf#page=2), [S4](../data/source/stat3.pdf#page=4); Nb, V, C, Mn, Mo, and P in [T2](../data/source/tanaka1981.pdf#page=2), [T17](../data/source/tanaka1981.pdf#page=17). | Connects alloy families and precipitates to recrystallization, transformation, strength, and toughness mechanisms. Symbols such as `Nb` remain exact aliases of their element names. |
| **PRECIPITATE** | An identified dispersed compound, not an element or bulk phase: Tanaka's fine `Nb(C,N)` and `V(C,N)` precipitates in [T2](../data/source/tanaka1981.pdf#page=2), [T12](../data/source/tanaka1981.pdf#page=12). The Russian article discusses carbonitride strengthening in [S5](../data/source/stat3.pdf#page=5), but does not justify inventing a specific precipitate formula there. | Enables evidence-backed paths such as Nb → Nb(C,N) → retarded recrystallization or precipitation hardening. Keep generic “carbonitride strengthening” as a process/mechanism when the compound is not identified. |
| **PHASE** | A constituent phase: austenite and ferrite in [S1](../data/source/stat3.pdf#page=1), [S4](../data/source/stat3.pdf#page=4); γ-austenite, α-ferrite, bainite, and martensite in [T1](../data/source/tanaka1981.pdf#page=1), [T4](../data/source/tanaka1981.pdf#page=4), [T23](../data/source/tanaka1981.pdf#page=23). | Makes transformation paths explicit: deformation of austenite → ferrite nucleation → final structure. Phase symbols γ/α need document context before resolution. |
| **MICROSTRUCTURE** | A morphology or phase arrangement: fine ferrite grain and Widmanstätten-like structure in [S1](../data/source/stat3.pdf#page=1), [S4](../data/source/stat3.pdf#page=4); elongated unrecrystallized austenite with deformation bands in [T1](../data/source/tanaka1981.pdf#page=1), [T5](../data/source/tanaka1981.pdf#page=5), ferrite–pearlite banding in [T17](../data/source/tanaka1981.pdf#page=17), and ferrite-plus-martensite dual-phase structure in [T23](../data/source/tanaka1981.pdf#page=23). | Bridges processing stages to strength/toughness outcomes. A phase name alone belongs to `PHASE`; its grain size, banding, or mixture belongs here. |
| **PROPERTY** | A resulting material characteristic: strength and toughness in [S1](../data/source/stat3.pdf#page=1), [S4](../data/source/stat3.pdf#page=4); yield stress, notch toughness, ductile-to-brittle transition temperature, and weldability in [T1–2](../data/source/tanaka1981.pdf#page=1), [T17–18](../data/source/tanaka1981.pdf#page=17). | Gives the graph outcome targets for route comparison and model evaluation. Mill productivity is an operational metric, not a material `PROPERTY`. |
| **PROCESS_CONDITION** | A controlled setting or operating range: finishing temperature, per-pass reduction, holding time, cooling rate, and water flow in [S2](../data/source/stat3.pdf#page=2), [S6](../data/source/stat3.pdf#page=6), [S8–9](../data/source/stat3.pdf#page=8); slab-reheating temperature, total reduction, finishing temperature, and cooling conditions in [T2](../data/source/tanaka1981.pdf#page=2), [T21](../data/source/tanaka1981.pdf#page=21). | Lets a traversal ask *under which conditions* a stage changes grain size or toughness. Preserve original numbers and units as attributes/evidence; do not create a node for each value. Outcome measurements belong to `PROPERTY`. |
| **MODEL** | A named or clearly defined explanatory/predictive relationship: the integral thermotechnical accelerated-cooling model in [S9](../data/source/stat3.pdf#page=9); the Hall–Petch relation in [T2](../data/source/tanaka1981.pdf#page=2), [T17](../data/source/tanaka1981.pdf#page=17), and the Zener–Hollomon relationship in [T5–6](../data/source/tanaka1981.pdf#page=5). | Connects conditions and microstructural variables to predicted quantities without treating an equation's OCR string as the whole scientific idea. |
| **FORMULA** | A legible, referenced mathematical expression: the cooling-unit water-flow equation in [S9](../data/source/stat3.pdf#page=9); Tanaka's recrystallized grain-size equation (3) in [T6](../data/source/tanaka1981.pdf#page=6) and Hall–Petch yield-stress equation (8) in [T17](../data/source/tanaka1981.pdf#page=17). | Allows a path from a model to its exact expression and defined variables. Require a source-page check before normalizing OCR-damaged symbols; keep the original expression and equation number. |

## Types removed or renamed

| Initial/current label | Decision | Reason |
| --- | --- | --- |
| `MATERIAL` | Replace with `ALLOY_FAMILY`, `STEEL_GRADE`, and `PRODUCT_FORM`. | “Steel” can otherwise become an over-connected hub mixing composition, grade, and physical form. |
| `PARAMETER` | Replace with `PROCESS_CONDITION`. | The unrestricted label mixes controllable temperatures/reductions with measured yield stress, grain size, and formula variables. |
| `ORGANIZATION` | Exclude from the domain graph; retain as document provenance. | Azovstal in [S1–2](../data/source/stat3.pdf#page=1), Kawasaki Steel in [T1](../data/source/tanaka1981.pdf#page=1), and citation organizations identify facilities/authors, but organization traversal is not the study's metallurgical question. Mill 3600 remains `EQUIPMENT`, not an organization. |
| Current `PRODUCT`, `PROCESS_SCHEME`, `COMPONENT` | Rename the first two to `PRODUCT_FORM` and `PROCESS_ROUTE`; drop generic `COMPONENT`. | A component could mean a mill part, a phase fraction, or a formula term. Use the narrower types above or an attribute. |
| `STANDARD` or generic `METHOD` from the project specification | Do not add. | The texts mention an API grade and named modeling/processing methods, but a generic standards/method bucket would add weak hubs. API X70 stays `STEEL_GRADE`; Hall–Petch stays `MODEL`. |

`PRECIPITATE`, already in the current configuration, remains because Tanaka explicitly discusses Nb(C,N)/V(C,N) and their mechanism. `PROCESS_ROUTE` and `PRODUCT_FORM` are narrower replacements for current labels. `COOLING_METHOD` is kept separate from `PROCESS` because comparing air, accelerated, controlled, and coiling cooling is central to these texts.

## Russian–English alias and non-alias policy

Use a shared alias table for both arms. Preserve the source spelling as evidence and resolve only the equivalences supported by context. The canonical English labels below are for matching; grades and formulas keep their exact written designations.

| Canonical concept | Russian forms in S | English forms or symbols in T | Resolution rule |
| --- | --- | --- | --- |
| Controlled rolling | `контролируемая прокатка`, `КП` ([S1](../data/source/stat3.pdf#page=1)) | `controlled rolling` ([T1](../data/source/tanaka1981.pdf#page=1)) | Same `PROCESS`. `ТМО` (thermomechanical treatment) is broader, not an alias. |
| Recrystallization | `рекристаллизация` ([S1](../data/source/stat3.pdf#page=1)) | `recrystallization` ([T1](../data/source/tanaka1981.pdf#page=1), [T5–6](../data/source/tanaka1981.pdf#page=5)) | Same general `PROCESS`; dynamic and static recrystallization remain distinct variants. |
| Austenite | `аустенит` ([S1](../data/source/stat3.pdf#page=1)) | `austenite`, contextual `γ` ([T1](../data/source/tanaka1981.pdf#page=1)) | Same `PHASE` when γ denotes the austenitic phase; retain the original symbol. |
| Ferrite | `феррит` ([S1](../data/source/stat3.pdf#page=1)) | `ferrite`, contextual `α` ([T1](../data/source/tanaka1981.pdf#page=1)) | Same `PHASE` when α denotes ferrite; ferrite grain size is a separate measurement. |
| Deformation | `деформация` ([S1](../data/source/stat3.pdf#page=1)) | `deformation` ([T1](../data/source/tanaka1981.pdf#page=1)) | Same general process. `обжатие` = rolling reduction, a more specific condition, not a full synonym. |
| Accelerated cooling | `ускоренное охлаждение`, `УО` ([S1](../data/source/stat3.pdf#page=1), [S5](../data/source/stat3.pdf#page=5)) | `rapid cooling` on the run-out table ([T21](../data/source/tanaka1981.pdf#page=21)) | Related `COOLING_METHOD` concepts; merge only when rate/apparatus context supports equivalence. Tanaka's `controlled cooling` is broader than `УО`. |
| Air cooling / holding | `охлаждение на воздухе`, `выдержка на воздухе` ([S2–3](../data/source/stat3.pdf#page=2)) | cooling/holding during a plate-mill delay ([T21](../data/source/tanaka1981.pdf#page=21)) | Related stages, but a delay is not automatically an air-cooling method unless the text says so. |
| Roughing / finishing | `черновая клеть`, `чистовая клеть` ([S2–3](../data/source/stat3.pdf#page=2)) | `rougher`, `finisher` ([T21](../data/source/tanaka1981.pdf#page=21)) | Match equipment roles; roughing/finishing *passes* are `PROCESS_STAGE`, not equipment. |
| Strength / toughness | `прочность`, `вязкость` in mechanical-property context ([S1](../data/source/stat3.pdf#page=1)) | `strength`, `toughness` ([T1](../data/source/tanaka1981.pdf#page=1)) | Link corresponding `PROPERTY` concepts; do not interpret `вязкость` here as fluid viscosity. |
| Finishing temperature | `температура конца прокатки` ([S2](../data/source/stat3.pdf#page=2)) | `finishing temperature` ([T21](../data/source/tanaka1981.pdf#page=21)) | Same `PROCESS_CONDITION` concept; retain different measured values per document/route. |

Do **not** merge `К–56`/`К–60` with `API X70`, low-pearlite steel with C–Mn–Nb steel, or accelerated cooling with all controlled cooling solely because they appear in similar process descriptions. Preserve `Ac3`, `Ar3`, γ, α, Nb(C,N), and units exactly; OCR variants are not aliases without page verification.

## Relationship patterns for later extraction

These are proposed edge roles, **not asserted graph results**:

- `PROCESS_ROUTE` **HAS_STAGE** `PROCESS_STAGE`; `PROCESS_STAGE` **USES_COOLING_METHOD** `COOLING_METHOD` and **USES_EQUIPMENT** `EQUIPMENT` ([S3–6](../data/source/stat3.pdf#page=3), [T21](../data/source/tanaka1981.pdf#page=21)).
- `STEEL_GRADE` **BELONGS_TO** `ALLOY_FAMILY`; a family **CONTAINS_ELEMENT** `CHEMICAL_ELEMENT`; an element **FORMS** `PRECIPITATE` only where a compound is stated ([S1](../data/source/stat3.pdf#page=1), [S5](../data/source/stat3.pdf#page=5), [T2](../data/source/tanaka1981.pdf#page=2), [T12](../data/source/tanaka1981.pdf#page=12)).
- `PROCESS` **TRANSFORMS** `PHASE` and **PRODUCES** `MICROSTRUCTURE`; microstructure **AFFECTS** `PROPERTY`. The documents connect deformation/recrystallization and cooling to ferrite refinement and strength/toughness ([S1](../data/source/stat3.pdf#page=1), [T1](../data/source/tanaka1981.pdf#page=1), [T5](../data/source/tanaka1981.pdf#page=5)).
- `MODEL` **EXPRESSED_BY** `FORMULA`; a formula **ESTIMATES** a condition or property only when its variables are defined in the source ([S9](../data/source/stat3.pdf#page=9), [T17](../data/source/tanaka1981.pdf#page=17)).

Attach document/page provenance to every extracted entity and relation. Store numerical values, units, ranges, route order, and equation numbers as evidence/attributes; avoid creating isolated nodes for each table entry or symbol. This preserves the ability to test cross-document paths without inflating graph noise.

## Cross-document traversal questions to test after indexing

1. **Controlled rolling → recrystallization → austenite/ferrite → toughness.** S1 describes changing the temperature and deformation regime to refine ferrite; T1 and T5 describe recrystallization, deformation bands, and ferrite nucleation. The path should keep stage-specific evidence rather than implying that every route has the same mechanism.
2. **Cooling → process route → microstructure/property.** Compare S's air hold and `КП+УО(+КП)` alternatives ([S3–6](../data/source/stat3.pdf#page=3)) with T's controlled cooling and plate/strip differences ([T2](../data/source/tanaka1981.pdf#page=2), [T21](../data/source/tanaka1981.pdf#page=21)). Do not equate the methods without matching context.
3. **Deformation → Nb-bearing alloy/precipitate → recrystallization → grain size.** S discusses reductions and Nb-bearing low-pearlite steels ([S1](../data/source/stat3.pdf#page=1), [S4](../data/source/stat3.pdf#page=4)); T explicitly links Nb(C,N) precipitation to retarded recrystallization and fine α grains ([T2](../data/source/tanaka1981.pdf#page=2), [T9–12](../data/source/tanaka1981.pdf#page=9)). The precipitate-specific edge belongs to T unless S's page evidence identifies it.
4. **Model → formula → measured outcome.** S's water-flow cooling model ([S9](../data/source/stat3.pdf#page=9)) and T's Hall–Petch yield-stress relation ([T17](../data/source/tanaka1981.pdf#page=17)) should be retrievable as different models, with equations checked against the PDFs.

## Configuration and index status

`configs/graphrag/entity_types.yaml` and both generated workspace settings use this shared list. The DIRTY graph has been indexed with these entity types; the CLEAN workspace has not yet been indexed. When the ontology or extraction prompt changes, regenerate and validate both workspaces, then rebuild both graphs before comparing them.

## Evaluation labels for the ontology

Use the canonical concepts and Russian/English aliases above to curate
`data/gold/entities.csv` and `data/gold/domain_terms.txt`. Store aliases as
pipe-separated variants on the reviewed canonical entity/term row. Keep the
cross-document traversal prompts above as candidates; enter only manually
reviewed seeds and expected entities into `data/gold/traversal_queries.csv`.
The evaluator's matching rules and score definitions are documented in
[metrics.md](metrics.md). Do not treat this proposal itself as gold annotation.
