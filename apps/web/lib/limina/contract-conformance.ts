import type { components } from "@/lib/limina/generated";
import type {
  ArtifactReview,
  Me,
  NotificationChannel,
  NotificationDelivery,
  NotificationRule,
  Project,
  RuntimeHealth,
} from "@/lib/limina/types";

type Schemas = components["schemas"];
type Assert<Value extends true> = Value;

// These exported compile-time witnesses keep the ergonomic presentation types
// assignable to their generated OpenAPI counterparts. The deterministic drift
// check catches endpoint changes; these catch incompatible hand-written views.
export type ProjectContractConforms = Assert<Project extends Schemas["ProjectResponse"] ? true : false>;
export type MeContractConforms = Assert<Me extends Schemas["MeResponse"] ? true : false>;
export type RuntimeHealthContractConforms = Assert<
  RuntimeHealth extends Schemas["HealthResponse"] ? true : false
>;
export type ArtifactReviewContractConforms = Assert<
  ArtifactReview extends Schemas["ArtifactReviewResponse"] ? true : false
>;
export type NotificationChannelContractConforms = Assert<
  NotificationChannel extends Schemas["NotificationChannelResponse"] ? true : false
>;
export type NotificationRuleContractConforms = Assert<
  NotificationRule extends Schemas["NotificationRuleResponse"] ? true : false
>;
export type NotificationDeliveryContractConforms = Assert<
  NotificationDelivery extends Schemas["NotificationDeliveryResponse"] ? true : false
>;
