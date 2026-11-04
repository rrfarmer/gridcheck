"use strict";

// EveJS's AIR New Player Experience, played by a real EVE client. This plugin adds no events,
// steps or tools: it carries the scenarios in scenarios/ and the Python driver they load into
// the client agent (scenarios/air/). It applies only in a tree that has the AIR runtime.

module.exports = {
  name: "air",
  apiVersion: 1,
  applies({ resolve }) {
    return resolve("services/npe/airNpeRuntime") ? true : { ok: false, reason: "no AIR runtime in this tree (no server/src/services/npe/airNpeRuntime.js)" };
  },
  tool: {},
};
