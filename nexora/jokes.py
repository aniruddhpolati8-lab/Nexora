from __future__ import annotations

import random
from typing import Optional


# ============================================================
# NEXORA JOKE DATABASE
# ============================================================
# Built-in joke database for Nexora.
#
# Categories:
#   football
#   team
#   player
#   general
#   short
#   question_answer
#   story
#   absurd
#
# Onana jokes intentionally excluded.
# ============================================================


JOKES = [

    # ========================================================
    # FOOTBALL JOKES
    # ========================================================

    {
        "id": "football_001",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "stadium", "wife"],
        "text": "My wife said I’m addicted to football stadiums and that she’s going to divorce me. I said, 'On what grounds?'"
    },

    {
        "id": "football_002",
        "category": "football",
        "type": "pun",
        "tags": ["football", "world_cup", "bolivia"],
        "text": "What did the referee say to the South American footballer who lied about deliberately handling the ball at the World Cup? I don’t Bolivia!"
    },

    {
        "id": "football_003",
        "category": "football",
        "type": "pun",
        "tags": ["football", "america", "kit", "new_jersey"],
        "text": "What is the best place in America to shop for a new soccer kit? New Jersey!"
    },

    {
        "id": "football_004",
        "category": "football",
        "type": "pun",
        "tags": ["football", "musketeers"],
        "text": "My brother plays football for a team called the Musketeers. They’ve started the season well with three wins and a draw, all 4-1 and one 4-all."
    },

    {
        "id": "football_005",
        "category": "football",
        "type": "pun",
        "tags": ["premier_league", "manchester_united", "old_trafford"],
        "text": "What is the chilliest ground in the Premier League? Cold Trafford."
    },

    {
        "id": "football_006",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "everton"],
        "text": "How many Everton fans does it take to screw in a light bulb? None – they’re quite happy living in the shadows."
    },

    {
        "id": "football_007",
        "category": "football",
        "type": "comparison",
        "tags": ["football", "leeds", "tea"],
        "text": "What’s the difference between Leeds United and a tea bag? The tea bag stays in the cup for longer."
    },

    {
        "id": "football_008",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "west_ham", "xbox"],
        "text": "What does a West Ham United fan do after winning the Premier League? Turn off the Xbox."
    },

    {
        "id": "football_009",
        "category": "football",
        "type": "story",
        "tags": ["football_manager", "newcastle"],
        "text": "I was playing Football Manager when I was offered the Newcastle job out of the blue. I knew it was a poor squad so I declined the offer. Then, I put the phone down and went back to playing Football Manager!"
    },

    {
        "id": "football_010",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "manchester_united", "tickets"],
        "text": "My mate left two Manchester United tickets on his car dashboard the other day. Someone smashed the window and left a couple more!"
    },

    {
        "id": "football_011",
        "category": "football",
        "type": "comparison",
        "tags": ["football", "fulham", "invisible_man"],
        "text": "What’s the difference between the Invisible Man and Fulham? You’ve got more chance of seeing the Invisible Man at a cup final."
    },

    {
        "id": "football_012",
        "category": "football",
        "type": "pun",
        "tags": ["football", "tottenham", "triangle"],
        "text": "What is the difference between Tottenham and a triangle? A triangle has three points."
    },

    {
        "id": "football_013",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "manchester_united", "old_trafford", "thunderstorm"],
        "text": "Why is Old Trafford the best place to go during a thunderstorm? There is absolutely no chance of any silverware striking there."
    },

    {
        "id": "football_014",
        "category": "football",
        "type": "pun",
        "tags": ["football", "arsenal", "manager", "cup"],
        "text": "Why does the Arsenal manager only drink tea? Because he can't find a cup."
    },

    {
        "id": "football_015",
        "category": "football",
        "type": "comparison",
        "tags": ["football", "chelsea", "pencil"],
        "text": "What do Chelsea FC and a broken pencil have in common? They both have no point, and they are incredibly expensive to replace."
    },

    {
        "id": "football_016",
        "category": "football",
        "type": "question_answer",
        "tags": ["football", "liverpool"],
        "text": "Why do Liverpool fans never hide and seek? Because they spend all their time talking about where they used to be."
    },

    {
        "id": "football_017",
        "category": "football",
        "type": "pun",
        "tags": ["football", "harry_kane", "trophy"],
        "text": "Harry Kane went to a bakery and asked for a trophy. The baker said, 'Sorry, we only make things with fillings, not empty shelves.'"
    },

    {
        "id": "football_018",
        "category": "football",
        "type": "pun",
        "tags": ["football", "lukaku", "boots", "first_touch"],
        "text": "Why does Romelu Lukaku wear such large boots? To accommodate his first touch, which always bounces five yards away."
    },

    {
        "id": "football_019",
        "category": "football",
        "type": "comparison",
        "tags": ["football", "darwin_nunez", "ufo"],
        "text": "What is the difference between Darwin Núñez and a UFO? People actually claim to have seen a UFO hit its target."
    },

    {
        "id": "football_020",
        "category": "football",
        "type": "pun",
        "tags": ["football", "antony", "right_turns"],
        "text": "Why did Antony get lost on his way to training? He could only make right turns."
    },

    {
        "id": "football_021",
        "category": "football",
        "type": "story",
        "tags": ["football", "todd_boehly", "chelsea"],
        "text": "Todd Boehly went to a library and tried to buy the building just because he liked one book."
    },

    {
        "id": "football_022",
        "category": "football",
        "type": "pun",
        "tags": ["football", "kompany", "kane", "bayern"],
        "text": "Bayern boss Vincent Kompany must have hurt his leg. He is always relying on a Kane."
    },

    {
        "id": "football_023",
        "category": "football",
        "type": "story",
        "tags": ["football", "relationship"],
        "text": "My partner just ended our relationship because of my obsession with football. I’m quite sad about it – we’d been dating for three seasons."
    },

    {
        "id": "football_024",
        "category": "football",
        "type": "pun",
        "tags": ["football", "goalkeeper"],
        "text": "My dad was renowned for 'thinking outside of the box'. Great guy, but a terrible goalkeeper."
    },

    {
        "id": "football_025",
        "category": "football",
        "type": "pun",
        "tags": ["football", "addiction", "kick"],
        "text": "Playing football is addictive and I want to stop but I just can’t seem to kick the habit."
    },

    {
        "id": "football_026",
        "category": "football",
        "type": "pun",
        "tags": ["football", "goalkeeper"],
        "text": "My girlfriend is the star goalie of her local football team… she’s a keeper."
    },

    {
        "id": "football_027",
        "category": "football",
        "type": "story",
        "tags": ["football", "wife", "90_minutes"],
        "text": "A wife says to her husband: 'Choose, it’s either me or football.' The husband responds: 'Give me 90 minutes to think.'"
    },

    {
        "id": "football_028",
        "category": "football",
        "type": "pun",
        "tags": ["football", "betting", "ladder"],
        "text": "Why did the football betting expert bring a ladder to the game? He heard the odds were stacked against him."
    },

    {
        "id": "football_029",
        "category": "football",
        "type": "pun",
        "tags": ["football", "tottenham", "bra"],
        "text": "Have you heard about the new Tottenham bra? It has a lot of support but no cups."
    },

    {
        "id": "football_030",
        "category": "football",
        "type": "pun",
        "tags": ["football", "wales", "world_cup"],
        "text": "What do you call a person from Wales in the FIFA World Cup final? The referee."
    },

    {
        "id": "football_031",
        "category": "football",
        "type": "pun",
        "tags": ["football", "grealish"],
        "text": "Jack Grealish goes to the doctor and says, 'It hurts when I touch my face, elbow and knee.' The doctor says, 'You’ve broken your finger.'"
    },

    {
        "id": "football_032",
        "category": "football",
        "type": "pun",
        "tags": ["football", "ange_postecoglou", "dog", "lead"],
        "text": "Why isn’t Ange Postecoglou allowed to keep a dog? Because he can’t keep hold of a lead."
    },

    {
        "id": "football_033",
        "category": "football",
        "type": "pun",
        "tags": ["football", "ben_mee"],
        "text": "Who is the most self-obsessed Premier League player? Ben Mee."
    },

    {
        "id": "football_034",
        "category": "football",
        "type": "pun",
        "tags": ["football", "griezmann"],
        "text": "Who is the slipperiest footballer on the planet? Antoine Grease-man."
    },

    {
        "id": "football_035",
        "category": "football",
        "type": "pun",
        "tags": ["football", "robert_sanchez", "virus"],
        "text": "My laptop has the Robert Sanchez virus – it can’t save anything!"
    },

    {
        "id": "football_036",
        "category": "football",
        "type": "pun",
        "tags": ["football", "ben_chilwell", "fridge"],
        "text": "Which player uses a fridge wisely? Ben Chilwell."
    },

    {
        "id": "football_037",
        "category": "football",
        "type": "pun",
        "tags": ["football", "erling_haaland"],
        "text": "Which striker comes from a funny country? Erling Ha-Ha-Land."
    },

    {
        "id": "football_038",
        "category": "football",
        "type": "pun",
        "tags": ["football", "jurrien_timber"],
        "text": "Which defender takes a long time to fall? Jurrien Timberrrrr!"
    },


    # ========================================================
    # GENERAL JOKES
    # ========================================================

    {
        "id": "general_001",
        "category": "general",
        "type": "story",
        "tags": ["hypnotist", "bar"],
        "text": "A man walks into a bar and orders a drink. The bartender says, 'I can’t serve you, you’re a hypnotist.' The man replies, 'Look into my eyes... you’re a cocktail shaker.'"
    },

    {
        "id": "general_002",
        "category": "general",
        "type": "question_answer",
        "tags": ["doctor", "arm"],
        "text": "I told my doctor that I broke my arm in two places. He told me to stop going to those places."
    },

    {
        "id": "general_003",
        "category": "general",
        "type": "pun",
        "tags": ["anti_gravity", "book"],
        "text": "I’m reading a book on anti-gravity. I just can't put it down."
    },

    {
        "id": "general_004",
        "category": "general",
        "type": "pun",
        "tags": ["flamingo"],
        "text": "My wife told me to stop impersonating a flamingo. I had to put my foot down."
    },

    {
        "id": "general_005",
        "category": "general",
        "type": "pun",
        "tags": ["haircut"],
        "text": "Did you get a haircut? No, I got them all cut."
    },

    {
        "id": "general_006",
        "category": "general",
        "type": "pun",
        "tags": ["restaurant", "moon"],
        "text": "Did you hear about the restaurant on the moon? Great food, no atmosphere."
    },

    {
        "id": "general_007",
        "category": "general",
        "type": "pun",
        "tags": ["dentist", "crown"],
        "text": "My dentist told me I need a crown. I said, 'I know, right? Finally, someone recognizes my royalty!'"
    },

    {
        "id": "general_008",
        "category": "general",
        "type": "pun",
        "tags": ["spreadsheet", "excel"],
        "text": "I excel at spreadsheets. Tom Microsoft Word."
    },

    {
        "id": "general_009",
        "category": "general",
        "type": "pun",
        "tags": ["clock", "time"],
        "text": "I ate a clock yesterday. It was very time-consuming."
    },

    {
        "id": "general_010",
        "category": "general",
        "type": "pun",
        "tags": ["velcro"],
        "text": "Velcro... what a rip-off."
    },

    {
        "id": "general_011",
        "category": "general",
        "type": "pun",
        "tags": ["elevator"],
        "text": "I love elevators. They are just so uplifting."
    },

    {
        "id": "general_012",
        "category": "general",
        "type": "question_answer",
        "tags": ["scarecrow", "award"],
        "text": "Why did the scarecrow win an award? Because he was outstanding in his field."
    },

    {
        "id": "general_013",
        "category": "general",
        "type": "question_answer",
        "tags": ["skeleton"],
        "text": "Why don't skeletons fight each other? They don't have the guts."
    },

    {
        "id": "general_014",
        "category": "general",
        "type": "pun",
        "tags": ["cheese"],
        "text": "What do you call cheese that isn't yours? Nacho cheese."
    },

    {
        "id": "general_015",
        "category": "general",
        "type": "question_answer",
        "tags": ["math"],
        "text": "Why was the math book sad? It had too many problems."
    },

    {
        "id": "general_016",
        "category": "general",
        "type": "pun",
        "tags": ["ocean", "beach"],
        "text": "What did the ocean say to the beach? Nothing, it just waved."
    },

    {
        "id": "general_017",
        "category": "general",
        "type": "question_answer",
        "tags": ["scientist", "atoms"],
        "text": "Why can't you trust atoms? Because they make up everything."
    },


    # ========================================================
    # SHORT STORIES
    # ========================================================

    {
        "id": "story_001",
        "category": "story",
        "type": "dialogue",
        "tags": ["job_interview", "honesty"],
        "text": (
            'Interviewer: "What would you say is your greatest weakness?"\n'
            'Candidate: "I am brutally honest."\n'
            'Interviewer: "I don’t think honesty is a weakness."\n'
            'Candidate: "I don’t care what you think."'
        )
    },

    {
        "id": "story_002",
        "category": "story",
        "type": "dialogue",
        "tags": ["dog", "talking_dog", "bar"],
        "text": (
            'A man walks into a bar with a dog. The bartender says, '
            '"No pets allowed." The man says, "But this is a talking dog! Watch." '
            'He looks at the dog and asks, "What’s on top of a house?" '
            'The dog barks, "Roof!" The bartender rolls his eyes. '
            'The man asks, "What does sandpaper feel like?" The dog barks, "Rough!" '
            'The bartender tells them to get out. On the sidewalk, the dog looks up '
            'at the man and says, "Should I have said smooth?"'
        )
    },

    {
        "id": "story_003",
        "category": "story",
        "type": "dark_humor",
        "tags": ["fortune_teller", "psychic"],
        "text": (
            'A man goes to a psychic. She looks into her crystal ball and says, '
            '"Your wife will die an untimely death." The man looks down, sighs, '
            'and asks, "Will I be acquitted?"'
        )
    },


    # ========================================================
    # ABSURD JOKES
    # ========================================================

    {
        "id": "absurd_001",
        "category": "absurd",
        "type": "pun",
        "tags": ["pirate", "bar", "steering_wheel"],
        "text": "A pirate walks into a bar with a steering wheel attached to his pants. The bartender asks, 'Hey, did you know you have a steering wheel in your trousers?' The pirate replies, 'Arrr, it’s driving me nuts.'"
    },

    {
        "id": "absurd_002",
        "category": "absurd",
        "type": "genie",
        "tags": ["genie", "government"],
        "text": "A guy finds a genie who grants him one wish. The guy says, 'I want to live forever.' The genie replies, 'I can't do that. Wish for something else.' The guy says, 'Fine, I want to die when the government fixes the economy.' The genie gasps, 'You clever bastard.'"
    },

]


# ============================================================
# INDEXES
# ============================================================

JOKES_BY_CATEGORY: dict[str, list[dict]] = {}

for joke in JOKES:
    category = joke["category"]
    JOKES_BY_CATEGORY.setdefault(category, []).append(joke)


JOKES_BY_TAG: dict[str, list[dict]] = {}

for joke in JOKES:
    for tag in joke.get("tags", []):
        JOKES_BY_TAG.setdefault(tag, []).append(joke)


# ============================================================
# JOKE FUNCTIONS
# ============================================================

def get_random_joke(
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    """
    Return a random joke.

    Example:
        get_random_joke()
        get_random_joke(category="football")
        get_random_joke(tag="arsenal")
    """

    if tag:
        candidates = JOKES_BY_TAG.get(tag.casefold(), [])

    elif category:
        candidates = JOKES_BY_CATEGORY.get(category.casefold(), [])

    else:
        candidates = JOKES

    if not candidates:
        return {
            "id": "fallback",
            "category": "general",
            "type": "fallback",
            "tags": [],
            "text": "I searched the joke vault and somehow found absolutely nothing. Impressive."
        }

    return random.choice(candidates)


def get_joke_text(
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> str:
    """Return only the joke text."""

    return get_random_joke(category=category, tag=tag)["text"]


def search_jokes(query: str, limit: int = 10) -> list[dict]:
    """
    Search jokes by words appearing in the joke text,
    category, type or tags.
    """

    query = query.casefold().strip()

    if not query:
        return []

    words = query.split()
    matches = []

    for joke in JOKES:
        searchable = " ".join([
            joke.get("text", ""),
            joke.get("category", ""),
            joke.get("type", ""),
            " ".join(joke.get("tags", [])),
        ]).casefold()

        score = 0

        for word in words:
            if word in searchable:
                score += 1

        if score:
            matches.append((score, joke))

    matches.sort(key=lambda item: item[0], reverse=True)

    return [joke for _, joke in matches[:limit]]


def get_categories() -> list[str]:
    """Return all available joke categories."""

    return sorted(JOKES_BY_CATEGORY.keys())


def get_tags() -> list[str]:
    """Return all available joke tags."""

    return sorted(JOKES_BY_TAG.keys())


def joke_count() -> int:
    """Return the number of jokes in the database."""

    return len(JOKES)


# ============================================================
# NEXORA-FRIENDLY INTERFACE
# ============================================================

def joke_response(
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    """
    Returns a response object that can be plugged directly
    into Nexora's assistant_response() system.
    """

    joke = get_random_joke(category=category, tag=tag)

    return {
        "type": "joke",
        "message": joke["text"],
        "joke_id": joke["id"],
        "category": joke["category"],
        "tags": joke["tags"],
    }


# ============================================================
# SIMPLE TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("NEXORA JOKE DATABASE")
    print("=" * 60)
    print(f"Total jokes: {joke_count()}")
    print(f"Categories: {', '.join(get_categories())}")
    print()
    print("Random joke:")
    print(get_joke_text())
