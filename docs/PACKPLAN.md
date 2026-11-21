# Pack-out plan

`src.decide.packplan` is a deterministic two-line scheduler. It consumes the
truth engine's serialized editions, usable stock, inbound arrivals and shift
windows. Each 30-minute bucket adds arrivals, then solves the small integer
packing problem for CE and Standard. Candidate points are the LP boundary
points (zero, each line's capacity and each shared-component stock boundary);
the best point for objective `w * CE + STD` is selected. This is exact for the
two-variable bucket problem because a linear objective reaches an integer
polytope boundary. The scheduler evaluates both fixed CE-first and STD-first
corners in every bucket, so weighted results are never worse in total units than
either baseline policy.

The report includes several weights, not a fabricated value for the unknown
loss `L` per missing Collector's copy. Its Pareto frontier shows the available
trade-off between CE and Standard units. `first_stop` identifies the first
component that prevents a line from using its planned rate in a bucket. A
what-if can move all arrivals of a part earlier, release quarantined units, or
restore usable stock; the returned delta is the counterfactual units and the
allocation section states which numbered pre-orders remain unfulfilled.

All 72,000 CE copies are numbered and pre-ordered, but the supplied data has no
customer-level order timestamps, tiers or regions. Therefore allocation is a
human decision owned by the Head of Procurement / Head of Sales. The CLI
reports three consequences: first-come by order number, highest-tier first,
and proportional region split. Ask for the missing fields before selecting
one; the engine does not silently choose a fairness policy.

Run:

```bash
python3 -m src.decide.packplan
python3 -m unittest tests.test_packplan -v
```

Limits: the model assumes each line can switch editions at bucket boundaries,
does not model changeover time, labour contention, carton staging or outbound
truck capacity, and excludes held inbound until a what-if explicitly releases
stock. These assumptions should be confirmed by DC-HAM operations before
committing a shift plan.
