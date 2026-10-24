// Products that can be trained in the browser. A new product (gripper, legged robot)
// adds one TrainingProduct here: its MJCF builder, its parameters and its fitness.
import { droneProduct } from "./drone";
import { gripperProduct } from "./gripper";
import type { TrainingProduct } from "./types";

export const PRODUCTS: Record<string, TrainingProduct<any>> = {
  [droneProduct.id]: droneProduct,
  [gripperProduct.id]: gripperProduct,
};

export function productFor(id: string): TrainingProduct<any> {
  const product = PRODUCTS[id];
  if (!product) throw new Error(`No browser training for product "${id}"`);
  return product;
}
