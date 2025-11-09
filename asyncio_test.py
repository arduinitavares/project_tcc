"""Example asyncio test file."""

import asyncio
import time


async def fetch_data(param: int) -> str:
    """Simulate an asynchronous data fetch operation."""
    print(f"Fetching data for: {param}")
    await asyncio.sleep(param)
    print(f"Data fetched for: {param}")

    return f"Result of {param}"


async def main():
    """Main async function to run tasks."""
    task1 = asyncio.create_task(fetch_data(1))
    task2 = asyncio.create_task(fetch_data(2))

    result2 = await task2
    print("Task 2 fully completed.")

    result1 = await task1
    print("Task 1 fully completed.")

    return result1, result2


t1 = time.perf_counter()
results = asyncio.run(main())
print(f"Results: {results}")
t2 = time.perf_counter()
print(f"Completed in {t2 - t1} seconds")


if __name__ == "__main__":
    asyncio.run(main())
