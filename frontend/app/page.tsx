import type { Metadata } from "next";
import Link from "next/link";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "Engineering knowledge that can show its work · Amalind",
  description:
    "A neurosymbolic engineering assistant for projects, inspectable rulepacks, and evidence-grounded answers.",
};

const WindowBar = ({ label }: { label: string }) => (
  <div className={styles.visualBar}>
    <span className={styles.visualDots} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
    <span>{label}</span>
  </div>
);

export default function Home() {
  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <aside className={styles.rail} aria-label="Homepage navigation">
          <a className={styles.wordmark} href="#top">
            <span className={styles.wordmarkMark} aria-hidden="true" />
            AMALIND
          </a>
          <nav className={styles.railNav}>
            <a href="#product">Product</a>
            <a href="#engine">Logic engine</a>
            <a href="#why">Why neuro&shy;symbolic</a>
            <a href="#start">Get started</a>
          </nav>
          <p className={styles.railFooter}>
            Engineering intelligence
            <br />
            grounded in evidence
          </p>
        </aside>

        <main className={styles.main}>
          <header className={styles.mobileHeader}>
            <a className={styles.wordmark} href="#top">
              <span className={styles.wordmarkMark} aria-hidden="true" />
              AMALIND
            </a>
            <nav aria-label="Mobile navigation">
              <a href="#product">Product</a>
              <a href="#why">Why</a>
              <Link href="/assistant">Enter app</Link>
            </nav>
          </header>

          <section className={styles.hero} id="top">
            <p className={styles.kicker}>Neurosymbolic AI for engineering</p>
            <h1 className={styles.heroTitle}>
              Engineering knowledge that can <span>show its work.</span>
            </h1>
            <div className={styles.heroBottom}>
              <div className={styles.heroActions}>
                <Link className={styles.primaryLink} href="/assistant">
                  Open assistant <span aria-hidden="true">↗</span>
                </Link>
                <a className={styles.secondaryLink} href="#product">
                  See how it works <span aria-hidden="true">↓</span>
                </a>
              </div>
              <p className={styles.heroIntro}>
                Amalind combines a conversational assistant with explicit engineering logic. Ask
                questions in plain language. Get answers tied to the rules, objects, and paths that
                made them true.
              </p>
            </div>
          </section>

          <div className={styles.proofStrip}>
            {[0, 1].map((copy) => (
              <div className={styles.proofTrack} aria-hidden="true" key={copy}>
                <span>
                  path(<b>pump_101</b>, valve_14)
                </span>
                <span>∧ status(valve_14, open)</span>
                <span>
                  ⇒ reachable(<b>vessel_204</b>)
                </span>
                <span>evidence: P-101 → V-14 → V-204</span>
              </div>
            ))}
          </div>

          <section className={styles.section} id="product" aria-label="Product capabilities">
            <div className={styles.sectionHead}>
              <div>
                <p className={styles.sectionLabel}>The product / four connected parts</p>
                <h2 className={styles.sectionTitle} id="capabilities-title">
                  From a question to an answer you can inspect.
                </h2>
              </div>
              <p className={styles.sectionIntro}>
                Each part is useful alone. Together, they turn diagrams, requirements, and
                engineering judgment into a reviewable knowledge system.
              </p>
            </div>

            <div className={styles.featureList}>
              <article className={styles.feature}>
                <span className={styles.featureIndex}>01 / ASK</span>
                <div className={styles.featureCopy}>
                  <h3>Assistant</h3>
                  <p>
                    Ask about a system the way you would ask an experienced engineer. Every claim
                    stays attached to its evidence.
                  </p>
                </div>
                <div className={styles.featureVisual} aria-label="Assistant answer example">
                  <WindowBar label="assistant / grounded answer" />
                  <p className={styles.chatQuestion}>
                    “Can P-101 still reach V-204 if valve V-14 is closed?”
                  </p>
                  <p className={styles.answerLine}>
                    No. V-14 is the only traversable connection between the pump discharge and
                    V-204. Closing it removes the path.
                  </p>
                  <div className={styles.evidence}>
                    <span>3 claims grounded</span>
                    <span>view evidence →</span>
                  </div>
                </div>
              </article>

              <article className={styles.feature}>
                <span className={styles.featureIndex}>02 / DEFINE</span>
                <div className={styles.featureCopy}>
                  <h3>Rulepacks</h3>
                  <p>
                    Package standards, checks, and team knowledge as readable rules. See the exact
                    logic before it runs, then reuse it across reviews.
                  </p>
                </div>
                <div className={styles.featureVisual} aria-label="Rulepack example">
                  <WindowBar label="rulepack / overpressure protection" />
                  <div className={styles.ruleStack}>
                    <div className={styles.rule}>
                      <span className={styles.ruleNo}>01</span>
                      <span>Relief path is present</span>
                      <span className={styles.ruleStatus}>SATISFIED</span>
                    </div>
                    <div className={styles.rule}>
                      <span className={styles.ruleNo}>02</span>
                      <span>Isolation risk is reviewed</span>
                      <span className={styles.ruleStatus}>SATISFIED</span>
                    </div>
                    <div className={styles.rule}>
                      <span className={styles.ruleNo}>03</span>
                      <span>Discharge destination is known</span>
                      <span className={styles.ruleStatus}>EVIDENCE</span>
                    </div>
                  </div>
                </div>
              </article>

              <article className={styles.feature}>
                <span className={styles.featureIndex}>03 / ORGANIZE</span>
                <div className={styles.featureCopy}>
                  <h3>Projects</h3>
                  <p>
                    Keep diagrams, conversations, and the rulepacks that govern them together.
                    Context carries forward without hiding where it came from.
                  </p>
                </div>
                <div className={styles.featureVisual} aria-label="Engineering project example">
                  <WindowBar label="project / north utilities rev. c" />
                  <div className={styles.projectDiagram} aria-hidden="true">
                    <span className={`${styles.node} ${styles.nodeOne}`} />
                    <span className={`${styles.node} ${styles.nodeTwo}`} />
                    <span className={`${styles.node} ${styles.nodeThree}`} />
                    <span className={`${styles.pipe} ${styles.pipeOne}`} />
                    <span className={`${styles.pipe} ${styles.pipeTwo}`} />
                  </div>
                  <div className={styles.evidence}>
                    <span>12 diagrams · 4 rulepacks</span>
                    <span>18 review threads</span>
                  </div>
                </div>
              </article>

              <article className={styles.feature}>
                <span className={styles.featureIndex}>04 / PROVE</span>
                <div className={styles.featureCopy}>
                  <h3>Logic engine</h3>
                  <p>
                    Run deterministic graph and Datalog reasoning beneath the conversation.
                    Conclusions are reproducible, inspectable, and bounded by known facts.
                  </p>
                </div>
                <div className={styles.featureVisual} aria-label="Logic engine example">
                  <WindowBar label="engine / query.dl" />
                  <pre className={styles.logicCode}>
                    <code>
                      <span className={styles.predicate}>reachable</span>(
                      <span className={styles.variable}>From</span>,{" "}
                      <span className={styles.variable}>To</span>) :-{"\n"}
                      {"  "}
                      <span className={styles.predicate}>connected</span>(
                      <span className={styles.variable}>From</span>,{" "}
                      <span className={styles.variable}>Next</span>),{"\n"}
                      {"  "}
                      <span className={styles.predicate}>open_path</span>(
                      <span className={styles.variable}>Next</span>),{"\n"}
                      {"  "}
                      <span className={styles.predicate}>reachable</span>(
                      <span className={styles.variable}>Next</span>,{" "}
                      <span className={styles.variable}>To</span>).{"\n\n"}
                      <span className={styles.predicate}>answer</span>(
                      <span className={styles.variable}>X</span>) :-{" "}
                      <span className={styles.predicate}>reachable</span>(pump_101,{" "}
                      <span className={styles.variable}>X</span>).
                    </code>
                  </pre>
                </div>
              </article>
            </div>
          </section>

          <section className={styles.engine} id="engine">
            <div className={styles.engineInner}>
              <div className={styles.sectionHead}>
                <div>
                  <p className={styles.sectionLabel}>Inside the logic engine</p>
                  <h2 className={styles.sectionTitle}>Language in. Proof out.</h2>
                </div>
                <p className={styles.sectionIntro}>
                  The model handles language. The engine handles entailment. Amalind keeps the two
                  responsibilities separate, then brings their results back together.
                </p>
              </div>
              <div className={styles.engineGrid}>
                <article className={styles.engineStep}>
                  <small>01 / INTERPRET</small>
                  <h3>Understand the question</h3>
                  <p>Turn the engineer&apos;s intent into a bounded query over known objects.</p>
                </article>
                <article className={styles.engineStep}>
                  <small>02 / REASON</small>
                  <h3>Execute explicit logic</h3>
                  <p>Evaluate graph paths and rules deterministically against project facts.</p>
                </article>
                <article className={styles.engineStep}>
                  <small>03 / EXPLAIN</small>
                  <h3>Return the witness</h3>
                  <p>Answer in plain language with the facts and rule trace attached.</p>
                </article>
              </div>
            </div>
          </section>

          <section className={`${styles.section} ${styles.neuro}`} id="why">
            <div>
              <h2 className={styles.sectionLabel}>Why neurosymbolic AI?</h2>
              <h3 className={styles.neuroTitle}>
                Fluent where it helps. <span>Formal where it matters.</span>
              </h3>
            </div>
            <div className={styles.neuroCopy}>
              <p>
                Language models are excellent at interpreting intent and explaining complex ideas.
                They should not be asked to silently invent the engineering facts underneath an
                answer.
              </p>
              <p>
                Symbolic reasoning gives those facts structure: explicit relationships, executable
                rules, and conclusions that can be checked again. The combination makes AI more
                useful without asking engineers to lower the standard of proof.
              </p>
              <p className={styles.neuroEquation}>
                <b>natural language</b> + explicit rules + project evidence = grounded decisions
              </p>
            </div>
          </section>

          <section className={styles.finalCta} id="start">
            <p>Start with a question</p>
            <h2>Bring your engineering context into the conversation.</h2>
            <Link className={styles.primaryLink} href="/assistant">
              Open assistant <span aria-hidden="true">↗</span>
            </Link>
          </section>

          <footer className={styles.footer}>
            <div className={styles.footerMeta}>
              <span>Neurosymbolic engineering intelligence</span>
              <br />
              <span>Prototype / 2026</span>
            </div>
            <Link href="/assistant">Enter workspace ↗</Link>
          </footer>
          <div className={styles.footerWordmark} aria-hidden="true">
            amalind
          </div>
        </main>
      </div>
    </div>
  );
}
