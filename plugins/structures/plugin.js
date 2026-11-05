"use strict";

// EveJS Upwell structures, played by a real EVE client: deploy, anchor, core, fit, fuel and
// use every citadel and refinery, moon mining, a war siege and the fuel-out path. This plugin adds
// no events, steps or tools: it carries the scenarios in scenarios/ and the Python driver they
// load into the client agent (scenarios/upwell/). It applies only in a tree with the structure
// runtime.

module.exports = {
  name: "structures",
  apiVersion: 1,
  applies({ resolve }) {
    return resolve("services/structure/structureState") ? true : { ok: false, reason: "no Upwell structure runtime in this tree (no server/src/services/structure/structureState.js)" };
  },
  tool: {},
};
