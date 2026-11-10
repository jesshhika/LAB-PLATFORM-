function getLaunchErrorMessage(status) {
  if (status === 429) return "Lab capacity reached, try again later";
  return `Could not launch lab (HTTP ${status}).`;
}

module.exports = { getLaunchErrorMessage };
