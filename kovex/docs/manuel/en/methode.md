# Role mining method

This document explains what Kovex computes, why, and how the correctness of
the result is verified. It is for whoever has to defend the method in front of
an auditor or a demanding client.

## The problem

We have a boolean matrix: identities in rows, rights in columns, a cell true
when the person holds the right. We are looking for a set of roles — subsets
of rights — and an assignment of people to those roles, such that the result
reproduces the matrix.

In its exact form the problem is **boolean matrix decomposition**, known to be
NP-hard. No tool solves it exactly at the scale of 20,000 identities and 8,000
rights; they all use heuristics. The honest question is therefore not "is this
optimal" but "what does the heuristic guarantee, and what does it cost".

## The three criteria that pull against each other

Every solution is judged on three axes, and improving one degrades the others.

**Coverage.** The share of real entitlements explained by the roles. Coverage
of 100 % with one role per person is trivial and worthless.

**Over-granting.** The rights the roles would grant to people who do not hold
them. This is the security cost of the simplification. High over-granting
turns a rationalisation project into a widening of access.

**Structural complexity.** The number of roles, their size, the number of
assignments. A solution nobody can read through has no operational value,
whatever its coverage.

Kovex reports all three quantities for every configuration. A tool that shows
only one of them is hiding the trade-off from you.

## The algorithms

### Exact grouping

Identities holding exactly the same set of rights form a group. Each group
yields one candidate role.

No parameter, nothing arbitrary, zero over-granting by construction. In
exchange, coverage is low: on real data, very few people have a rigorously
identical portfolio.

This is the reference: any role produced this way is beyond dispute.

### Approximate grouping

Two identities are brought together if their sets of rights are similar within
a threshold θ. The role kept is the intersection, or a closure of the group's
rights, depending on the variant.

θ is **the** parameter of the product. It has no good universal value: it
encodes your security policy's tolerance for over-granting. That is why Kovex
does not fix it and provides the full curve instead.

### Set cover

Once the candidates are produced, a subset must be chosen that covers the most
entitlements with the fewest roles. This is a **set cover** problem, also
NP-hard.

Kovex uses a lazy greedy heuristic: at each step, the role that brings the
most new entitlements. This heuristic has a known theoretical guarantee — the
result is at worst a logarithmic factor above the optimum. That is not the
optimum, it is a bound, and it is what can honestly be claimed.

The lazy variant exploits the submodularity of the gain to avoid re-evaluating
every candidate at each step. The result is identical to the naive greedy one;
only the computation time changes.

### Consolidation

Two very close roles are merged, or one absorbs the other. This reduces
structural complexity without touching coverage, or barely touching it.

This point was settled by measurement, not by principle. Three strategies were
compared on a repository with known ground truth:

- **merge by intersection**: collapses correctness — 4 exact roles recovered
  out of 15, against 12 without consolidation. Discarded.
- **absorption**: keeps recall at 0.973, unchanged, while halving structural
  complexity. Kept.
- **choice of representative**: taking the best ranked keeps recall; taking
  another drops it to 0.797 or 0.830. The representative is therefore always
  the best ranked.

The consolidation threshold has its own exploration screen too. Marginal
efficiency — complexity gained per point of recall lost — shows a clear
maximum, which gives a defensible starting point.

## Baseline rights

A right held by almost every identity carries no discriminating information.
Leaving it in the matrix has two effects: it inflates coverage artificially,
and it makes every role look alike.

Kovex detects them on an adjustable prevalence threshold and lets them be
removed before business mining. The threshold is left to the user: depending
on the organisation, "almost everyone" starts at 80 % or at 98 %.

## Correctness validation

A role mining tool verified only on client data is not verified at all: on
real data, nobody knows the right answer.

Kovex embeds a generator of **ground-truth repositories**. It builds a
population whose roles are known by construction, adds noise to it — extra
grants, missing grants — then runs the mining on the result.

The roles produced are matched to the planted roles by Jaccard similarity,
which gives a measured precision and recall, not an estimated one.

A command-line bench replays this validation, either synthetically or on
public matrices read locally. It runs offline, on an isolated server, with no
client data.

That apparatus is what allowed the consolidation choices above to be settled
by measurement. It is also what makes it possible, before every delivery, to
establish that a change has not degraded correctness.

## What Kovex does not do

Out of honesty, and because a tool that claims to do everything is credible on
nothing:

- it does not guarantee optimality — no tool can at this scale;
- it does not name roles on its own: a name is only proposed when a language
  model is connected and its use opened by the administrator, and it is the
  analyst who keeps or discards it;
- it does not detect that a repository value is filler ("missing information"
  treated as a real application);
- it does not replace a human review. It makes one workable.
