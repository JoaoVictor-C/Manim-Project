"""The script of "Momentum, Torque and Angular Momentum": narration sentences per section.

Spoken text only; the visuals of each section are in scenes.py and in script.md (generated).
Each sentence is one subtitle cue and one beat the animation waits for.
"""

SECTIONS = [
    {
        "id": "hook",
        "title": "Why does the skater speed up?",
        "visual": "Top view of a skater: two hands on arms that pull in. The spin speeds up with no push.",
        "sentences": [
            "Watch a figure skater spin.",
            "She pulls her arms in, and suddenly she spins much faster.",
            "No one pushed her. No motor turned on.",
            "So where did the extra speed come from?",
            "The answer hides in three connected ideas: momentum, torque, and angular momentum.",
            "Let's build them one at a time.",
        ],
    },
    {
        "id": "momentum",
        "title": "1 · Linear momentum",
        "visual": "Two blocks of different mass at the same speed; momentum arrows. Then a collision with "
        "a live total-momentum readout, ending on F = dp/dt.",
        "sentences": [
            "We start with the simplest one: linear momentum.",
            "Momentum is mass times velocity. It is written p equals m v.",
            "It is a vector, so it points the same way the object moves.",
            "A heavy truck and a light bicycle can move at the same speed, "
            "but the truck carries far more momentum, and is far harder to stop.",
            "Now watch two carts collide.",
            "Each cart changes its momentum, but the total, before and after, is exactly the same.",
            "When no outside force acts, total momentum is conserved.",
            "And what changes momentum? A force. Force is the rate of change of momentum.",
        ],
    },
    {
        "id": "torque",
        "title": "2 · Torque",
        "visual": "A wrench on a bolt; the force angle and the lever arm change while the torque "
        "value is computed live; the perpendicular part of the force is shown.",
        "sentences": [
            "Forces make things speed up in a straight line. To make something rotate, we need torque.",
            "Imagine pushing on a wrench to turn a bolt.",
            "Torque is the distance from the pivot, r, crossed with the force, F.",
            "Its size is r F sine theta, where theta is the angle between them.",
            "Push far from the bolt, and the torque is large. Push close, and it is small.",
            "Push straight along the wrench, with theta equal to zero, and there is no torque at all.",
            "Only the part of the force that is perpendicular to r turns the bolt.",
            "Torque points along the axis of rotation, and the right hand rule tells us which way.",
        ],
    },
    {
        "id": "inertia",
        "title": "3 · Moment of inertia",
        "visual": "Two dumbbells with the same torque: masses near the axis spin up faster. Then the "
        "table of linear and rotational partners.",
        "sentences": [
            "Rotation has its own version of mass. We call it the moment of inertia, I.",
            "For point masses, I is the sum of m times r squared.",
            "Notice that distance counts squared. Mass far from the axis is much harder to spin.",
            "Newton's second law now has a rotating twin: torque equals I times alpha, "
            "where alpha is the angular acceleration.",
            "Every linear idea has a rotational partner: position and angle, velocity and angular "
            "velocity, mass and moment of inertia, force and torque, and momentum and angular momentum.",
        ],
    },
    {
        "id": "angular",
        "title": "4 · Angular momentum",
        "visual": "A particle on a circle with r and p arrows, L pointing out of the screen; a spinning "
        "disk with L along its axis; then tau = dL/dt.",
        "sentences": [
            "Now we can define angular momentum.",
            "For a single particle, it is the position vector r, crossed with the momentum p.",
            "For a spinning object, this simplifies to L equals I omega.",
            "A planet circling the Sun, a spinning top, a wheel: all of them carry angular momentum.",
            "Its direction follows the right hand rule. Curl your fingers the way it spins, "
            "and your thumb points along L.",
            "And just as force changes momentum, torque changes angular momentum.",
        ],
    },
    {
        "id": "conservation",
        "title": "5 · Conservation of angular momentum",
        "visual": "The skater again with live I, omega and L readouts: arms out, arms in. Then a "
        "planet on an eccentric orbit that speeds up near the Sun.",
        "sentences": [
            "Here is the payoff. If no external torque acts, angular momentum is conserved.",
            "Back to our skater. With her arms stretched out, her moment of inertia is large, "
            "and she spins slowly.",
            "When she pulls them in, I drops.",
            "But L equals I omega must stay constant, so omega has to go up.",
            "Half the moment of inertia means twice the spin rate.",
            "The same law makes a planet sweep faster when it swings close to the Sun, "
            "and it is why a diver tucks into a tight ball.",
        ],
    },
    {
        "id": "recap",
        "title": "Recap",
        "visual": "Three cards: momentum, torque, angular momentum, each with its equation.",
        "sentences": [
            "Let's recap.",
            "Momentum, p equals m v, measures motion in a straight line.",
            "Torque, tau equals r cross F, is what twists.",
            "Angular momentum, L equals I omega, measures spinning motion, "
            "and when there is no torque, it never changes.",
            "Next time you see a skater spin, you'll know the secret.",
        ],
    },
]
