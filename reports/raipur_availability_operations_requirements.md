# Raipur Availability Operations Requirements

Approval status: **APPROVAL REQUIRED – OPERATIONS DATA MISSING**

The live source must maintain slot-based availability for these approved Raipur services: Staycation Combo, Daycation Package, Pontoon Boat, Kayak, Speed Boat, Aqua Cycle, Jet Ski, Water Bike, Inflatable Sofa Ride, Bumper Boat, Kids' Paddle Boat, Pontoon Celebration, Floating Gazebo, Jetty Gazebo, Houseboat Celebration, and Party Boat Celebration.

For every slot, operations must provide the approved service, Raipur location, date (`YYYY-MM-DD`), start and end time (`HH:MM` 24-hour), total capacity, available capacity, operational status, verification timestamp, responsibility owner, and approval status.

Capacity must be zero or greater, and available capacity must not exceed total capacity. Valid statuses are `available`, `limited`, `full`, `closed`, `weather_hold`, `maintenance`, and `verification_required`.

Availability must be re-verified at least every 30 minutes. For weather holds, set `weather_hold`, verify the affected slots, and assign the operations owner. For maintenance, set `maintenance`, verify the affected slots, and assign the operations owner. Do not create a slot, capacity, or timing until operations has approved it.
