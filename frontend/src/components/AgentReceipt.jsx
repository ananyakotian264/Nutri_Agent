function describeStep(step) {
  if (step.type === "plan") return `Checking ${step.tool.replaceAll("_", " ")}`;
  if (step.type === "observation") return `Received results from ${step.tool.replaceAll("_", " ")}`;
  return "Nutrition entry complete";
}

export default function AgentReceipt({ trace = [] }) {
  if (!trace.length) return null;
  return <details className="agent-details">
    <summary><span className="agent-status-dot" />How this entry was prepared <span className="agent-step-count">{trace.filter((step) => step.type === "plan").length} steps</span></summary>
    <ol>{trace.filter((step) => step.type !== "final_answer").map((step, index) => <li key={`${step.type}-${index}`}><span className={step.type === "observation" ? "trace-marker received" : "trace-marker"} />{describeStep(step)}</li>)}</ol>
    <p>Nutrition estimates can be incomplete and may vary from your actual portion.</p>
  </details>;
}
