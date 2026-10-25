// TMDB URL Interceptor
// Intercepts blocked api.themoviedb.org and redirects to working api.tmdb.org
// Fixes ISP DPI / SNI handshake drops on Indian & regional networks (Jio, Airtel, ACT)
const https = require('https');
const http = require('http');

function patchUrl(url) {
  if (typeof url === 'string') {
    return url.replace('api.themoviedb.org', 'api.tmdb.org');
  }
  return url;
}

function patchOptions(options) {
  if (!options || typeof options !== 'object') return;
  if (options.hostname === 'api.themoviedb.org') {
    options.hostname = 'api.tmdb.org';
  }
  if (options.host === 'api.themoviedb.org' || options.host === 'api.themoviedb.org:443') {
    options.host = 'api.tmdb.org' + (options.port ? ':' + options.port : '');
  }
  if (options.servername === 'api.themoviedb.org') {
    options.servername = 'api.tmdb.org';
  }
  if (options.headers) {
    if (options.headers.host === 'api.themoviedb.org') {
      options.headers.host = 'api.tmdb.org';
    }
    if (options.headers.Host === 'api.themoviedb.org') {
      options.headers.Host = 'api.tmdb.org';
    }
  }
}

function wrapRequest(origFn) {
  return function(...args) {
    let [url, options, cb] = args;
    if (typeof url === 'string') {
      args[0] = patchUrl(url);
      if (options && typeof options === 'object') {
        patchOptions(options);
      }
    } else if (url instanceof URL) {
      if (url.hostname === 'api.themoviedb.org') {
        url.hostname = 'api.tmdb.org';
      }
      if (options && typeof options === 'object') {
        patchOptions(options);
      }
    } else if (url && typeof url === 'object') {
      patchOptions(url);
    }
    return origFn.apply(this, args);
  };
}

https.request = wrapRequest(https.request);
https.get = wrapRequest(https.get);
http.request = wrapRequest(http.request);
http.get = wrapRequest(http.get);

if (globalThis.fetch) {
  const origFetch = globalThis.fetch;
  globalThis.fetch = function(input, init) {
    if (typeof input === 'string') {
      input = patchUrl(input);
    } else if (input instanceof URL) {
      if (input.hostname === 'api.themoviedb.org') {
        input.hostname = 'api.tmdb.org';
      }
    } else if (input && typeof input === 'object' && input.url) {
      if (typeof input.url === 'string' && input.url.includes('api.themoviedb.org')) {
        input = new Request(patchUrl(input.url), input);
      }
    }
    return origFetch.call(this, input, init);
  };
}

console.log('[TMDB Interceptor] Successfully initialized: api.themoviedb.org -> api.tmdb.org');
