import React, { useState } from "react";
import StepUpload from "./components/StepUpload.jsx";
import StepPersona from "./components/StepPersona.jsx";
import Chat from "./components/Chat.jsx";

const STEPS = ["Add data", "Create agent", "Chat"];

export default function App() {
  const [step, setStep] = useState(0);
  const [agentName, setAgentName] = useState("joker");

  return (
    <div className="app">
      <header>
        <h1>Joke Platform</h1>
        <div className="steps">
          {STEPS.map((s, i) => (
            <span key={s} className={"pill" + (i === step ? " on" : "")}>
              {i + 1}. {s}
            </span>
          ))}
        </div>
      </header>

      {step === 0 && <StepUpload onNext={() => setStep(1)} />}
      {step === 1 && (
        <StepPersona
          onBack={() => setStep(0)}
          onNext={(name) => {
            setAgentName(name);
            setStep(2);
          }}
        />
      )}
      {step === 2 && <Chat agentName={agentName} onBack={() => setStep(1)} />}
    </div>
  );
}
