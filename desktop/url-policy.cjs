"use strict";
function parsed(v){try{return new URL(String(v||"").trim())}catch{return null}}
function normalizeServerUrl(v){
  const u=parsed(v);
  if(!u||u.username||u.password||u.search||u.hash||!u.hostname)return null;
  if(u.protocol!=="https:"&&u.protocol!=="http:")return null;
  u.pathname=u.pathname.replace(/\/+$/,"")||"/";
  return u.toString();
}
function isSameOrigin(v,s){const a=parsed(v),b=parsed(s);return !!(a&&b&&a.origin===b.origin&&["https:","http:"].includes(a.protocol))}
function isSafeExternal(v){const u=parsed(v);return !!(u&&!u.username&&!u.password&&(u.protocol==="https:"||u.protocol==="http:"||u.protocol==="mailto:"))}
// Google refuses OAuth inside embedded browsers, so this one-time handoff path on the
// BigBang server opens in the system browser instead of the app window.
const HANDOFF_PATH=/^\/integrations\/google-sheets\/browser\/[A-Za-z0-9_-]{20,100}$/;
function isBrowserHandoff(v,s){const u=parsed(v);return !!(u&&isSameOrigin(v,s)&&!u.search&&!u.hash&&HANDOFF_PATH.test(u.pathname))}
module.exports={isBrowserHandoff,isSafeExternal,isSameOrigin,normalizeServerUrl};
