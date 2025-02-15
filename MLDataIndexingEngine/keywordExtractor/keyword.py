from keybert import KeyBERT
import random
import json
import requests as req

def create_title(dat3 ):
    title = [
        [text_lowercase(dat3["Papers"][i]["title"])]
        for i in dat3["Papers"]
        if "title" in dat3["Papers"][i]
    ]

    for i in dat3["Datasets"]:
        ret = [text_lowercase(dat3["Datasets"][i]["name"]), text_lowercase(dat3["Datasets"][i]["description"]) ]
        title.append(ret)
    random.shuffle(title)
    return title

def text_lowercase(text):
    return text.lower()

def get_keywords(dat3,n):
    x = {}
    for i in range(2):
      kw_model = KeyBERT()
      title = create_title(dat3)
      title = [i for j in title for i in j]
      title = " ".join(title)
      keyword = kw_model.extract_keywords(title, keyphrase_ngram_range=(1,1), top_n = n, stop_words='english', 
                                    use_mmr=True, diversity=0.2)

      for i in keyword:
        if i[0] in x:
          x[i[0]] += i[1]
        else:
          x[i[0]] = i[1]
    x = key
    x = sorted(x.items(), key=lambda item: item[1])
    return {x[len(x)-i-1][0]: x[len(x)-i-1][1] for i in range(n)}

def main(n):   
    response = req.get("https://sparclink-f151d-default-rtdb.firebaseio.com/.json")
    dataset = response.json()
    dat3 = dataset["ikP4sIT5PJMWFNCKG5eof5RN2Em1"]
    ret = get_keywords(dat3, n)
    print(ret)
    with open('data.json', 'w') as jsonfile:
         json.dump(ret, jsonfile)
    return json.dumps(ret, indent = 2)
