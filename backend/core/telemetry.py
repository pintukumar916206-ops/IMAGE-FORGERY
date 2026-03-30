import time
from fastapi import Request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

REQUEST_COUNT = Counter(
    "api_requests_total",
    "Total number of requests received",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "api_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"]
)

ANALYSIS_TASK_COUNT = Counter(
    "forgery_analysis_tasks_total",
    "Total number of image analysis tasks submitted"
)

async def prometheus_middleware(request: Request, call_next):

    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    if request.url.path != "/api/metrics":
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(process_time)
        
    return response

def metrics_endpoint():

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
