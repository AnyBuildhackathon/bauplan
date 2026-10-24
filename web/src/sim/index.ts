// Public surface of the browser simulation, for the trainer, the stress test and firmware.
export { runRollouts, sharedPool, RolloutPool, defaultPoolSize, type RolloutBatch } from "./pool";
export { PRODUCTS, productFor } from "./products";
export { droneProduct, DRONE_GAINS, DRONE_TARGET, type DroneSpec } from "./drone";
export { CrossEntropy, toParams, fromParams } from "./es";
export type { Params, ParamSpec, Perturbation, RolloutJob, RolloutResult, TrainingProduct, Episode } from "./types";
