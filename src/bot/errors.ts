export class TtScrapError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly requestId: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "TtScrapError";
  }
}

export class PartialDeliveryError extends Error {
  constructor(readonly successfulCalls: number, readonly requestId: string, message = "Telegram delivery was only partially completed") {
    super(message);
    this.name = "PartialDeliveryError";
  }
}
