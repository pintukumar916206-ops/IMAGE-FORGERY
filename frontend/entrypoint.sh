#!/bin/sh

# Inject runtime environment variables into compiled static assets
if [ -d "/usr/share/nginx/html/assets" ]; then
    for file in /usr/share/nginx/html/assets/*.js; do
        if [ -f "$file" ]; then
            sed -i "s|__VITE_API_URL__|${VITE_API_URL:-http://localhost:8000/api}|g" "$file"
        fi
    done
fi

exec nginx -g 'daemon off;'
