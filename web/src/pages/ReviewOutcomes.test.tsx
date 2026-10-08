import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ReviewQueue } from "./ReviewQueue";
import { checkDecision } from "./reviewOutcome";

// Concept Review decision outcomes, rendered in StrictMode as main.tsx does. A
// stateful fixture backend lets a write either never arrive ("not sent"), or be
// committed and then lose its response ("lost response"), the case browser
// acceptance reproduced.
afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = (body: unknown) => Reply | Promise<Reply>;

function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const reviewable = (id: number) => ({
  unit_id: id,
  kind: "grammar",
  canonical: `unit ${id}`,
  statement: `Énoncé ${id}`,
  example: null,
  confidence: 0.9,
  candidate_identity: { target: `cible ${id}`, pedagogical_intent: "grammar", scope: "", identity_features: {} },
  signature: "{...}",
});

const concept = (id: number, target: string) => ({
  id,
  identity_schema_version: "fr_l2_concept_identity_v1",
  target,
  pedagogical_intent: "grammar",
  scope: "",
  identity_features: {},
  signature: "{...}",
  preferred_unit_id: null,
  state: "orphaned",
  lifecycle_state: "normal",
  support_state: "orphaned",
  created_at: "t",
  updated_at: "t",
});

type Mode =
  | "ok"
  | "not-sent"
  | "lost"
  | { reject: number; error: string }
  | { slow: ReturnType<typeof deferred> }
  // The request never arrives, but something else changes the backend meanwhile.
  | { notSentButElsewhere: () => void };

// A minimal backend for units 5 and 6 and concept #42 (an exact match for unit 5).
function backend() {
  const memberships = new Map<number, { concept_id: number; link_id: number; updated_at: string }>();
  const invalid = new Set<number>();
  const distinctions: Array<{ id: number; unit_id: number; concept_id: number }> = [{ id: 3, unit_id: 5, concept_id: 42 }];
  const links: Array<{ id: number; unit_id: number; concept_id: number; relation: string; status: string }> = [];
  const concepts = [concept(42, "cible 5")];
  let nextId = 100;
  const writeMode = new Map<string, Mode>();
  const calls: Array<{ method: string; path: string }> = [];
  const reads = new Map<string, Mode>();

  // commit applies a write to the fixture state, as the real backend would.
  const commit = (key: string, body: Record<string, unknown>): unknown => {
    const unitId = Number(key.match(/knowledge-units\/(\d+)/)?.[1] ?? body.seed_unit_id);
    if (key.endsWith("/concept-links/same")) {
      const link = nextId++;
      memberships.set(unitId, { concept_id: body.concept_id as number, link_id: link, updated_at: "t" });
      return { id: link, unit_id: unitId, concept_id: body.concept_id, relation: "same", status: "accepted" };
    }
    if (key === "POST /api/concepts") {
      const identity = body.identity as { target: string };
      const created = { ...concept(nextId++, identity.target) };
      concepts.push(created);
      const link = nextId++;
      memberships.set(unitId, { concept_id: created.id, link_id: link, updated_at: "t" });
      return { concept: created, link: { id: link } };
    }
    if (key.endsWith("/concept-distinctions")) {
      const d = { id: nextId++, unit_id: unitId, concept_id: body.concept_id as number };
      distinctions.push(d);
      return d;
    }
    if (key.endsWith("/concept-links/relation")) {
      const l = { id: nextId++, unit_id: unitId, concept_id: body.concept_id as number, relation: body.relation as string, status: "accepted" };
      links.push(l);
      return l;
    }
    if (key.endsWith("/invalid")) {
      invalid.add(unitId);
      memberships.delete(unitId);
      return { unit_id: unitId, invalid: true, current_membership: null, judgment: { id: nextId++ } };
    }
    throw new Error(`no commit for ${key}`);
  };

  const write = (key: string): Handler => async (body) => {
    const mode = writeMode.get(key) ?? "ok";
    if (mode === "not-sent") return "network-error";
    if (typeof mode === "object" && "notSentButElsewhere" in mode) {
      mode.notSentButElsewhere();
      return "network-error";
    }
    if (typeof mode === "object" && "reject" in mode) return { status: mode.reject, body: { error: mode.error } };
    if (typeof mode === "object" && "slow" in mode) {
      const reply = await mode.slow.promise;
      if (reply !== "network-error") commit(key, body as Record<string, unknown>);
      return reply;
    }
    const result = commit(key, body as Record<string, unknown>);
    return mode === "lost" ? "network-error" : { status: 201, body: result };
  };

  const read = (key: string, answer: () => unknown): Handler => async () => {
    const mode = reads.get(key);
    if (mode && typeof mode === "object" && "reject" in mode) {
      reads.delete(key);
      return { status: mode.reject, body: { error: mode.error } };
    }
    if (mode && typeof mode === "object" && "slow" in mode) {
      reads.delete(key);
      await mode.slow.promise;
    }
    return { body: answer() };
  };

  const handlers: Record<string, Handler> = {
    "GET /api/reviewable-units": read("reviewable", () => ({
      reviewable_units: [5, 6].filter((id) => !memberships.has(id) && !invalid.has(id)).map(reviewable),
    })),
    "GET /api/concepts": read("concepts", () => ({ concepts })),
    "GET /api/concepts/42": read("concept42", () => ({ concept: concepts[0], links: links.filter((l) => l.concept_id === 42) })),
    "POST /api/concepts": write("POST /api/concepts"),
  };
  for (const id of [5, 6]) {
    handlers[`GET /api/knowledge-units/${id}/concept-membership`] = read(`membership${id}`, () => ({ unit_id: id, current_membership: memberships.get(id) ?? null }));
    handlers[`GET /api/knowledge-units/${id}/concept-resolution`] = read(`resolution${id}`, () => ({
      unit_id: id,
      decision: id === 5 ? "matched" : "no_match",
      matches: id === 5 ? [concepts[0]] : [],
    }));
    handlers[`GET /api/knowledge-units/${id}/concept-distinctions`] = read(`distinctions${id}`, () => ({ unit_id: id, distinctions: distinctions.filter((d) => d.unit_id === id) }));
    handlers[`GET /api/knowledge-units/${id}/invalid`] = read(`invalid${id}`, () => ({ unit_id: id, invalid: invalid.has(id), history: invalid.has(id) ? [{ id: 99, judgment: "invalid" }] : [] }));
    for (const suffix of ["concept-links/same", "concept-distinctions", "concept-links/relation", "invalid"]) {
      handlers[`POST /api/knowledge-units/${id}/${suffix}`] = write(`POST /api/knowledge-units/${id}/${suffix}`);
    }
  }
  // The NEW CONCEPT check reads the created concept by ID.
  const conceptById = (id: number) => concepts.find((c) => c.id === id);

  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(input), "http://localhost").pathname;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path });
    let handler = handlers[`${method} ${path}`];
    const byId = path.match(/^\/api\/concepts\/(\d+)$/);
    if (!handler && method === "GET" && byId && conceptById(Number(byId[1]))) {
      handler = async () => ({ body: { concept: conceptById(Number(byId[1])), links: [] } });
    }
    const reply = handler ? await handler(body) : { status: 404, body: { error: "not found" } };
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;

  return {
    writeMode,
    reads,
    memberships,
    distinctions,
    links,
    invalid,
    posts: (suffix: string) => calls.filter((c) => c.method === "POST" && c.path.endsWith(suffix)).length,
  };
}

async function renderQueue() {
  const result = render(
    <StrictMode>
      <ReviewQueue />
    </StrictMode>,
  );
  await screen.findByText("Énoncé 5");
  await waitFor(() => expect(screen.getByRole("button", { name: "SAME → selected" })).toBeEnabled());
  return result;
}

const decision = (name: string) => screen.getByRole("button", { name });
const panel = () => screen.queryByRole("region", { name: "Unknown decision outcome" });

async function banner(role: "status" | "alert", text: string | RegExp): Promise<HTMLElement> {
  const matches = (el: HTMLElement) =>
    typeof text === "string" ? (el.textContent ?? "").includes(text) : text.test(el.textContent ?? "");
  let found: HTMLElement | undefined;
  await waitFor(() => {
    found = screen.queryAllByRole(role).find(matches);
    expect(found, `no ${role} containing ${String(text)}`).toBeDefined();
  });
  return found as HTMLElement;
}

describe("Missing response: never reported as failure", () => {
  it("request never arrived: unknown outcome, check finds nothing, stays blocked, no resend", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", "not-sent");
    await renderQueue();
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "cible éditée" } });
    fireEvent.click(decision("NEW CONCEPT"));

    const unknown = await banner("alert", "Outcome unknown.");
    expect(unknown).toHaveTextContent('No response was received for NEW CONCEPT "cible éditée" with SAME on unit #5, so it may or may not have been recorded. It was not sent again.');
    expect(unknown).not.toHaveTextContent(/could not be recorded|failed/i);
    await waitFor(() => expect(panel()).toHaveTextContent("Not visible on the server yet: The unit has no current SAME membership."));
    expect(panel()).toHaveTextContent("The original request may still be in progress on the server, or may never have arrived.");
    for (const name of ["SAME → selected", "NEW CONCEPT", "DISTINCT", "INVALID"]) expect(decision(name)).toBeDisabled();
    // The identity draft is kept for an informed retry.
    expect(screen.getByLabelText("target")).toHaveValue("cible éditée");
    expect(b.posts("/api/concepts")).toBe(1);
  });

  it("committed NEW CONCEPT with a lost response: the check finds it and the unit leaves the queue", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", "lost");
    await renderQueue();
    fireEvent.click(decision("NEW CONCEPT"));

    const notice = await banner("status", /Unit #5: the server shows NEW CONCEPT "cible 5" with SAME is stored \(The unit now belongs to concept #\d+ \("cible 5"\), matching the drafted identity\.\), so the unit left the queue\./);
    expect(notice).toBeInTheDocument();
    await screen.findByText("Énoncé 6");
    expect(screen.queryByText("Énoncé 5")).not.toBeInTheDocument();
    expect(b.posts("/api/concepts")).toBe(1);
    expect(b.memberships.has(5)).toBe(true);
  });

  it.each([
    { name: "SAME → selected", suffix: "/concept-links/same", found: "The unit's current SAME membership is concept #42" },
    { name: "INVALID", suffix: "/invalid", found: "The unit is INVALID" },
  ])("committed $name with a lost response is found and the unit leaves the queue", async ({ name, suffix, found }) => {
    const b = backend();
    b.writeMode.set(`POST /api/knowledge-units/5${suffix}`, "lost");
    await renderQueue();
    fireEvent.click(decision(name));
    await banner("status", found);
    await screen.findByText("Énoncé 6");
    expect(b.posts(`/api/knowledge-units/5${suffix}`)).toBe(1);
  });

  it("committed DISTINCT with a lost response: only an event newer than the baseline counts", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    // Event #3 existed before sending; the stored new event must be newer.
    await banner("status", /Found on the server: A new DISTINCT event #\d+ is stored\. DISTINCT from concept #42 is stored\./);
    // A DISTINCT does not change membership; the unit stays and decisions are possible again.
    expect(screen.getByText("Énoncé 5")).toBeInTheDocument();
    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
    await banner("status", "Unit #5's membership and exact matches re-read from the server.");
    expect(b.distinctions.filter((d) => d.unit_id === 5)).toHaveLength(2);
  });

  it("DISTINCT that never arrived is not mistaken for the older stored event", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "not-sent");
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(panel()).toHaveTextContent("No DISTINCT event newer than the one before sending is stored."));
    expect(decision("NEW CONCEPT")).toBeDisabled();
  });

  it("committed relation with a lost response is found in the concept's event history", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/relation", "lost");
    await renderQueue();
    fireEvent.click(decision("BROADER"));
    await banner("status", /Found on the server: A new BROADER event #\d+ for this unit is stored\./);
    expect(b.links).toHaveLength(1);
    expect(b.posts("/concept-links/relation")).toBe(1);
  });
});

describe("Informed recovery", () => {
  it("a failed check is reported; Check again finds the stored decision", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    await renderQueue();
    // The baseline read happens first; fail only the check's read that follows the POST.
    const original = globalThis.fetch;
    let failNextDistinctionRead = false;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "POST" && path.endsWith("/concept-distinctions")) failNextDistinctionRead = true;
      else if (failNextDistinctionRead && path.endsWith("/concept-distinctions")) {
        failNextDistinctionRead = false;
        return new Response(JSON.stringify({ error: "could not fetch distinctions" }), { status: 500, headers: { "Content-Type": "application/json" } });
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("DISTINCT"));
    const failed = await banner("alert", "Could not check the server for DISTINCT from concept #42: (500) could not fetch distinctions");
    expect(failed).toBeInTheDocument();
    expect(decision("NEW CONCEPT")).toBeDisabled();

    fireEvent.click(within(panel() as HTMLElement).getByRole("button", { name: "Check again" }));
    await banner("status", /Found on the server: A new DISTINCT event #\d+ is stored\./);
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("allowing another decision is explicit, explains the duplicate risk, and resends nothing", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "not-sent");
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));
    await waitFor(() => expect(panel()).toHaveTextContent("Not visible on the server yet"));

    fireEvent.click(screen.getByRole("button", { name: "Allow another decision for unit #5…" }));
    const group = screen.getByRole("group", { name: "Allow another decision for unit #5" });
    expect(group).toHaveTextContent("appends a new event, so sending it again after the first was stored records it twice");
    fireEvent.click(within(group).getByRole("button", { name: "Allow another decision" }));

    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
    expect(panel()).toHaveTextContent("You allowed another decision for unit #5 although the outcome of DISTINCT from concept #42 is still unknown.");
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("an explicit server rejection is definite: no reconciliation and no block", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/same", { reject: 422, error: "validation error\nconcept is retired" });
    await renderQueue();
    fireEvent.click(decision("SAME → selected"));
    await banner("alert", "The server did not record SAME → concept #42 (422) validation error\nconcept is retired.");
    expect(panel()).toBeNull();
    await waitFor(() => expect(decision("NEW CONCEPT")).toBeEnabled());
  });
});

describe("Slow writes, unit switches, and unmount", () => {
  it("a slow write locks decisions and unit switches until the server answers", async () => {
    const b = backend();
    const slow = deferred();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", { slow });
    await renderQueue();
    fireEvent.click(decision("DISTINCT"));

    await screen.findByText(/Sending DISTINCT from concept #42 for unit #5…/);
    expect(screen.getByRole("button", { name: "skip →" })).toBeDisabled();
    for (const name of ["SAME → selected", "NEW CONCEPT", "INVALID"]) expect(decision(name)).toBeDisabled();
    fireEvent.click(decision("DISTINCT"));

    await act(async () => {
      slow.resolve({ status: 201, body: { id: 7 } });
    });
    await banner("status", "Recorded DISTINCT: unit is NOT concept #42.");
    expect(screen.getByRole("button", { name: "skip →" })).toBeEnabled();
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("an unknown outcome stays with its unit: another unit is unaffected, and a late check lands on its own unit", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-distinctions", "lost");
    const slowCheck = deferred();
    await renderQueue();
    // Delay the check's read (the second distinctions read after the baseline).
    let distinctionReads = 0;
    const original = globalThis.fetch;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "GET" && path === "/api/knowledge-units/5/concept-distinctions") {
        distinctionReads += 1;
        if (distinctionReads === 2) await slowCheck.promise;
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("DISTINCT"));
    await banner("alert", "Outcome unknown.");
    await screen.findByText("Checking the server for DISTINCT from concept #42 on unit #5…");

    fireEvent.click(screen.getByRole("button", { name: "skip →" }));
    await screen.findByText("Énoncé 6");
    expect(panel()).toBeNull();
    expect(screen.queryByText(/Outcome unknown/)).not.toBeInTheDocument();
    await waitFor(() => expect(decision("INVALID")).toBeEnabled());

    await act(async () => {
      slowCheck.resolve({ body: null });
    });
    expect(screen.queryByText(/Found on the server/)).not.toBeInTheDocument();
    expect(screen.getByText("Énoncé 6")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "← previous" }));
    await screen.findByText("Énoncé 5");
    await banner("status", /Found on the server: A new DISTINCT event #\d+ is stored\./);
    expect(b.posts("/concept-distinctions")).toBe(1);
  });

  it("unmounting while a write is pending applies nothing afterwards", async () => {
    const b = backend();
    const slow = deferred();
    b.writeMode.set("POST /api/concepts", { slow });
    const { unmount } = await renderQueue();
    fireEvent.click(decision("NEW CONCEPT"));
    unmount();
    await act(async () => {
      slow.resolve("network-error");
    });
    expect(b.posts("/api/concepts")).toBe(1);
  });
});

describe("checkDecision for paths the queue cannot reach directly", () => {
  const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

  it("REASSIGN is found only when the membership moved to the requested concept", async () => {
    globalThis.fetch = vi.fn(async () => reply({ unit_id: 5, current_membership: { concept_id: 7, link_id: 2, updated_at: "t" } })) as unknown as typeof fetch;
    expect(await checkDecision({ kind: "same", unitId: 5, conceptId: 9, reassign: true }, null)).toEqual({
      found: false,
      text: "The unit's current SAME membership is concept #7, not #9.",
    });
    expect((await checkDecision({ kind: "same", unitId: 5, conceptId: 7, reassign: true }, null)).found).toBe(true);
  });

  it("NEW CONCEPT without SAME is found by its normalized identity in the catalog", async () => {
    globalThis.fetch = vi.fn(async () => reply({ concepts: [concept(8, "Cible  Nouvelle")] })) as unknown as typeof fetch;
    const identity = { target: "cible nouvelle", pedagogical_intent: "Grammar", scope: "", identity_features: {} };
    expect(await checkDecision({ kind: "new", unitId: 5, identity, seedAsSame: false }, null)).toEqual({
      found: true,
      text: "Concept #8 with this identity exists.",
    });
  });
});

describe("Evidence must match the decision, not just any change", () => {
  it("a relation that never arrived is not matched by an older stored event of the same kind", async () => {
    const b = backend();
    b.links.push({ id: 50, unit_id: 5, concept_id: 42, relation: "broader", status: "accepted" });
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/relation", "not-sent");
    await renderQueue();
    fireEvent.click(decision("BROADER"));
    await waitFor(() => expect(panel()).toHaveTextContent("No BROADER event newer than the one before sending is stored."));
    expect(decision("NEW CONCEPT")).toBeDisabled();
  });

  it("NEW CONCEPT is not found when the unit was resolved elsewhere to a different identity", async () => {
    const b = backend();
    b.writeMode.set("POST /api/concepts", {
      notSentButElsewhere: () => b.memberships.set(5, { concept_id: 42, link_id: 77, updated_at: "t" }),
    });
    await renderQueue();
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "cible éditée" } });
    fireEvent.click(decision("NEW CONCEPT"));
    await waitFor(() =>
      expect(panel()).toHaveTextContent('The unit now belongs to concept #42 ("cible 5"), whose identity differs from the draft.'),
    );
    expect(screen.getByText("Énoncé 5")).toBeInTheDocument();
  });

  it("a resolving decision found while viewing another unit removes that unit, not the one shown", async () => {
    const b = backend();
    b.writeMode.set("POST /api/knowledge-units/5/concept-links/same", "lost");
    const slowCheck = deferred();
    await renderQueue();
    let membershipReads = 0;
    const original = globalThis.fetch;
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET") === "GET" && path === "/api/knowledge-units/5/concept-membership") {
        membershipReads += 1;
        if (membershipReads === 1) await slowCheck.promise;
      }
      return original(input, init);
    }) as typeof fetch;

    fireEvent.click(decision("SAME → selected"));
    await screen.findByText("Checking the server for SAME → concept #42 on unit #5…");
    fireEvent.click(screen.getByRole("button", { name: "skip →" }));
    await screen.findByText("Énoncé 6");

    await act(async () => {
      slowCheck.resolve({ body: null });
    });
    await banner("status", "Unit #5: the server shows SAME → concept #42 is stored");
    expect(screen.getByText("Énoncé 6")).toBeInTheDocument();
    expect(screen.getByText("unit 1 of 1")).toBeInTheDocument();
  });
});
