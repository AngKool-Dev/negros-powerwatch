#!/bin/bash
# Cloudflare Pages build script
# Copies frontend files to public/ directory
mkdir -p public
cp -r templates/* public/ 2>/dev/null || true
cp -r static/* public/ 2>/dev/null || true
cp config.js public/ 2>/dev/null || true
