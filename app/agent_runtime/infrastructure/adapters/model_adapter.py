from app.agent_runtime.application.ports import ModelPolicy
from app.model_gateway import AGENT_INSTRUCTION, POLICIES, ModelGateway, ModelTaskKind, estimate_tokens


class ModelAdapter:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def policy(self) -> ModelPolicy | None:
        if not self.gateway.enabled:
            return None
        policy = POLICIES[ModelTaskKind.AGENT]
        return ModelPolicy(
            AGENT_INSTRUCTION, self.gateway.provider.value, self.gateway.config.base_url,
            self.gateway.config.model, policy.max_input_tokens, policy.max_output_tokens,
        )

    estimate_tokens = staticmethod(estimate_tokens)

    def candidate(self, material: str, *, answered: bool) -> dict:
        return self.gateway.agent_candidate(material, answered=answered)
