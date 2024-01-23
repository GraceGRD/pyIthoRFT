import asyncio
import logging
import aioconsole

from IthoRFT.remote import IthoRFTRemote

logging.basicConfig(level=logging.DEBUG)


async def cli():
    while True:
        await asyncio.sleep(0)  # Yield control to the event loop

        try:
            command = await aioconsole.ainput(
                "Enter a command (e.g., "
                "'pair', 'night', 'auto', 'low', 'high', 'timer10', 'timer20', 'timer30'"
                "'start', 'stop', 'rq'): \n"
            )
            if command == "pair":
                itho_remote.pair()
            elif (
                command == "night"
                or command == "auto"
                or command == "low"
                or command == "high"
                or command == "timer10"
                or command == "timer20"
                or command == "timer30"
            ):
                itho_remote.command(command)
            elif command == "start":
                itho_remote.start_task()
            elif command == "stop":
                itho_remote.stop_task()
            elif command == "rq":
                itho_remote.request_data()
            else:
                print("Unknown command")
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    loop = None
    itho_remote = IthoRFTRemote(port="COM8", remote_address="29:114646", unit_address="18:126620", log_to_file=True)

    async def main():
        itho_remote.start_task()
        asyncio.create_task(cli())

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("Program interrupted by user. Exiting...")
        tasks = asyncio.all_tasks(loop)
        for tasks in tasks:
            tasks.cancel()
    finally:
        loop.close()
