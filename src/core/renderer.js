import * as THREE from "three";
import { FOG_FAR, FOG_NEAR, RENDER_PIXEL_RATIO_MAX, SKY_COLOR } from "../utils/constants.js";

export function createRenderer(canvas) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    powerPreference: "high-performance",
  });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, RENDER_PIXEL_RATIO_MAX));
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.sortObjects = true;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(SKY_COLOR);
  scene.fog = new THREE.Fog(SKY_COLOR, FOG_NEAR, FOG_FAR);

  return { renderer, scene };
}

export function resizeRenderer(renderer, camera) {
  const width = window.innerWidth;
  const height = window.innerHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}
