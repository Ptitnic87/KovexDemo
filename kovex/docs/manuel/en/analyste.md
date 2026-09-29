# Analyst manual

This manual is for the person who uses Kovex: who runs the analyses, reads the
proposed roles, and decides to approve or reject them. It assumes no knowledge
of the algorithms.

## What Kovex does, in one sentence

Kovex reads who holds which rights, looks for groups of people who hold the
same rights, and offers to turn those groups into roles. One role replaces
dozens of individual grants with a single decision.

## The vocabulary

**Identity.** A person, with their attributes: job title, department, contract
type. Kovex presupposes none of these attributes: they are the columns of your
file, whatever they happen to be.

**Right.** An elementary authorisation inside an application: a security
group, a profile, an entitlement.

**Entitlement.** The fact that an identity holds a right. This is the raw
material: without it there is nothing to analyse.

**Application role.** A set of rights that belong together technically.
Discovered by mining.

**Business role.** A set of application roles and rights, granted by a rule
over identity attributes — for example "every nurse in department X". This is
what makes automatic granting possible.

**Business rule of a role.** What the members of a role have in common,
expressed over the attributes of your repository — "department = Accounting
*and* status = Manager". Kovex looks for it after the fact, on a role already
found: mining can say which rights belong together, not why.

**Rule reliability.** Among the people the rule designates, the share that
actually holds the role. What is missing to reach 100 % is the over-granting
you would accept by applying the rule as it stands.

**Explanatory power.** How many times better the rule identifies members than
a random draw. At 1 it teaches nothing — and this is a common trap: on a large
repository, a tiny regularity becomes statistically certain without being worth
anything. "51 % of members carry this flag, against 50 % in the population" is
an indisputable fact and a useless rule.

**Baseline right. A right that almost everyone holds: mail access, network
access. It carries no information for telling one job apart from another, and
it saturates the analysis if left in.

## The normal path

### 1. Check data quality first

The **Data quality** tab is not a formality. Mining run on inconsistent data
produces inconsistent roles, and nothing in the result will say so.

Look first at:

- **Orphan rights** and **orphan users**: entitlements pointing at a right or
  a person missing from the repository. They take part in no analysis.
- **Broken assignments**: the number of unusable *rows*.
- **Unassigned rights**: candidates for decommissioning, with no effect on
  mining but useful for governance.
- **Repository duplicates**: an identifier present twice skews every count.

A check shown as "—" is not at zero: it could not be computed, for lack of an
associated column in the configuration. Do not read it as "no anomaly".

The **Show details** button on each anomaly opens the full list of the
identifiers concerned, filterable and exportable to CSV. That list is what you
hand to the owner of the repository.

### 2. Detect baseline rights

Before business mining, run birth-right detection. A right held by 95 % of
identities does not help tell one job from another: leaving it in the analysis
produces huge roles that all look alike.

The threshold is yours. The lower it is, the more rights you remove, the more
distinguishing the remaining roles are — but the greater the risk of removing
a right that genuinely characterised a large population.

### 3. Run application mining

Two modes.

**Exact**: groups the identities that hold *exactly* the same set of rights.
No parameter to set, nothing arbitrary. Result: few roles, very pure, and low
coverage — reality is rarely that clean.

**Approximate**: groups the identities whose sets of rights are *similar*
within a threshold θ. Covers far more people, at the cost of grants in excess.

Two parameters frame the result:

- **Minimum users**: below it, a group is not a role, it is a coincidence.
  Three is a reasonable floor.
- **Minimum rights**: a "role" with a single right brings nothing that a
  direct grant does not already bring.

### 4. Choose θ rather than suffer it

This is the point where most tools leave you alone with a default value.
Kovex gives you the curve.

The **θ selection** screen sweeps a series of thresholds and plots, for each
one, two quantities that pull against each other:

- **coverage**: the share of real entitlements explained by the roles;
- **over-granting**: the rights the roles would give to people who do not hold
  them today.

θ = 1 grants no entitlement in excess. Lowering θ increases coverage *and*
over-granting. There is no good value in the absolute: there is the value your
security policy tolerates. Read the curve, first set the maximum acceptable
over-granting, then take the threshold that covers the most without exceeding
that limit — usually the lowest θ that respects it. Enter the limit on screen:
that is the threshold it points to.

### 5. Read a proposed role

For each role, four figures matter:

- **Number of users**: the population the role would cover.
- **Number of rights**: the size of the role. A role of 200 rights is not a
  role, it is a whole department.
- **Coverage**: the share of those users' entitlements the role explains.
- **Over-granting**: what the role would give in excess.

A role with non-zero over-granting is not disqualified by that alone. The
question is: are those excess rights harmless, or sensitive? A role that
over-grants read access to a directory is not a role that over-grants access
to a patient record.

### 5b. Ask for the business explanation of a role

The **Explanation** tab of the validation window answers the question the
application owner will ask: *what do these people have in common?*

Pick the attributes to combine — these are the columns of your files — and set
your requirements. They are yours, not the product's:

| Setting | What it decides |
|---|---|
| Expected reliability | Below it, the rule is flagged as indefensible. |
| Minimum share of members explained | The more you require, the broader the rule, and the less reliable. |
| Minimum explanatory power | Discards attributes that teach nothing. |
| Accepted risk of coincidence | Maximum probability that the match is fortuitous. |
| Number of combined criteria | A longer rule is more precise and less readable. |

Kovex returns **the most reliable rule that still explains the share of members
you require**. It does not settle the trade-off for you: adding a criterion
raises reliability and lowers the number of members explained.

The **what speaks for it, what speaks against it** diagnosis lists the findings
one by one, from the most blocking to the most reassuring, each with its
figure. It is deliberately not an overall score: a single percentage cannot be
challenged, whereas a committee must be able to object point by point.

Two findings deserve particular attention:

- **Exceptions** are the members the rule does not describe. These are the ones
  a committee reviews one by one.
- **Over-granting** counts the people the rule would designate although they do
  not hold the role today. This is the security cost of simplification.

A role without a rule is not a bad role: it is a role your attributes do not
describe. This happens when the identity repository does not carry the
dimension that actually structures those entitlements — a project, an on-call
rotation, seniority.

### 5c. The name suggested by a model

If your administrator has enabled the semantic annotator, the Explanation tab
suggests a name and a description. **Nothing applies until you take the
suggestion**: it fills the fields only when you ask, and you remain responsible
for what you approve.

Before any request, the screen shows which model is queried, what will be sent
to it, and **whether that data leaves the server**. By default the model only
sees the number of rights and members: no labels, no attribute values, no
already chosen names. What you see announced is exactly what leaves.

If your administrator allows already validated names, the model receives a few
roles from your catalogue as examples and follows your naming convention. They
are picked among the roles closest to this one — a computation that stays on
the server.

With no annotator configured, the slot says so and you name the role by hand —
that is normal operation, not a failure.

### 6. Approve or reject

**Approve** places the role in the knowledge base. It becomes visible in the
map and serves as a basis for later analyses.

**Reject** sets it aside for good. The rejection is remembered by the
fingerprint of the role's rights, not by its name: the same role will not be
proposed again at the next mining under a different label.

Give reasons for your rejections. The reason is recorded in the audit trail,
and it is what will explain, six months from now, why that role does not
exist.

### 7. Compose a business role

The composer assembles approved application roles, adds individual rights and
exceptions, and produces a business role that can be granted by an HR rule.

The rule is a strict equality over identity attributes. An identity whose
attribute is empty matches nothing — deliberately: a missing value must never
be read as "matches everything".

### 8. Review the catalogue later

A role is a rule, and a rule ages with the data. Six months after approval, the
population the rule designates has changed, and so have the entitlements its
members hold.

Above the roles, the catalogue therefore shows a **model review**: the
comparison between the figures you had in front of you when you decided and
today's. A population that has shrunk, one that has grown, a role that has
fallen below the minimum headcount, over-granting that has appeared, two roles
that now duplicate each other. Every finding carries both of its figures — the
old one and the new one — because a gap without its starting point cannot be
acted upon.

A role composed by hand has no figures recorded at creation time: its card
shows today's measurements and states that there is no gap to measure.

This review **corrects nothing**. It observes. An approved role is a governance
decision, and it may already have been provisioned in your identity management
tool: revisiting that decision is yours to do.

The threshold beyond which a gap becomes a finding is set in the workspace
configuration: a repository of three hundred identities and one of three
hundred thousand do not move on the same scale.

### 9. Applying a proposal, and what the export says about it

A finding may carry a **proposal**: remove from the role entitlements its
members do not hold, add entitlements they all already hold, merge two roles
that duplicate each other, remove a role that has fallen below the minimum
headcount. Every proposal states what the figure at stake would become —
deciding without that is deciding blind.

Two of them can be applied from the screen, because they only touch a role's
entitlements. The other two make a role disappear when it may already be
provisioned in your identity management tool: they are shown and explained,
never applied from here.

Restricting a role has a counterpart, and the screen says so: a role may
legitimately grant what its members do not hold yet — that is what a
harmonising model does. The threshold beyond which Kovex stops reading a gap as
harmonisation is set in the workspace configuration.

**An applied role keeps its identifier and gains a version.** The previous
version is kept with its date, its author and the finding that motivated it,
and the audit trail carries the same elements: "why did this role change on
3 March" can be answered without reopening the data.

That is also what the export gives you: every role carries its version and what
it has become since the last document produced — new, changed, unchanged.
Without that, the integrator receives a changed role they believe is new, and
creates a duplicate. A preview does not move that mark; only a document
actually produced does.

### 10. Reopening a role from the catalogue

The catalogue showed only a name and two counters. The **View detail** button
opens what the role actually contains: its holders, its entitlements, and for
each one the share of its members who already hold it.

That last column is the one that matters. "This role grants 340 entitlements in
excess" cannot be acted on; "this entitlement, four members in a hundred hold
it" can.

The same window carries the name and the description — changing them
**versions** the role, for the same reason changing its entitlements does — and
a button that asks a model for a name suggestion, when you have configured one.
The suggestion fills the field; it does not save itself.

**Removing a role from the catalogue** is done from this window too. A reason is
required. The role is not erased: it stays readable with your reason, your name
and its date, and the candidate it came from goes back to being undecided — in
other words, it will be proposed to you again at the next mining run.

## What is recorded

Every governance decision is recorded in the **audit trail**: approval,
rejection, mining runs with their parameters, exports, configuration changes.
The trail is chained by fingerprint: an after-the-fact modification is
detectable.

That means two things for you. Your decisions are defensible — you can show
when, and on which parameters, a role was approved. And they are attributable
— the trail carries your name.

## Common mistakes

**Running mining before looking at data quality.** The result will look clean
and be wrong underneath.

**Looking for the "optimal" θ.** There is none. There is a trade-off, and it
is yours to make.

**Approving a role without looking at its over-granting.** That is how a role
mining project ends up widening access instead of narrowing it.

**Ignoring baseline rights.** They make every role look like every other and
inflate coverage artificially.
