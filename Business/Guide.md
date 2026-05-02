# Contextbased Prompting 
### **Prompt engineering, but smart!**

The previous idea of giving prompts engineered to fit specific usecases, is smart enough, but it also lacks the much needed; context of the task. 

The differences between context- and no-context prompting are:
### Zero-shot prompting
- Providing no context or examples --> the machine has to figure out what is what, and can get it from previous chats if needed.
    - "The zero-shot prompt directly instructs the model to perform a task without any additional examples to steer it." (Prompting Guide)
- Keep it short, simple and useable (words are filler! They eat tokens and understandability.)

### Few-shot prompting
- Providing one (or more) examples in the prompt, to steer the model. This can be effective when attaching documents, parts of texts as an example, giving context from tasks etc
    - "Few-shot prompting can be used as a technique to enable in-context learning where we provide demonstrations in the prompt to steer the model to better performance." (Prompting Guide)

### Chain-of-thought prompting
- Giving the model information, that automatically makes it think step-by-step; it follows the given logic, and uses it to provide the proper answer. 
    - "Chain of thought prompting simulates human-like reasoning processes by breaking down elaborate problems into manageable, intermediate steps that sequentially lead to a conclusive answer.2 This step-by-step problem-solving structure aims to help ensure that the reasoning process is clear, logical and effective." (IBM study)

- Zero-shot CoT: "This approach is particularly valuable when dealing with novel or diverse problem types where tailored training data might not be available." --> Giving the model no specific examples, but enabling the model to work using learnt logic.
    - "“What is the capital of a country that borders France and has a red and white flag?”, a model that uses zero-shot CoT would draw on its embedded geographic and flag knowledge to deduce steps leading to Switzerland as the answer, despite not being explicitly trained on such queries." (IBM Study)
    
<br><br>
**Example with SQL and Drools:**
```
Prompt: Based on the principles of CoT Zero-shot, provide a short example of it for an SQL task related to a new Drools rule --> 


You want an AI to generate SQL that supports a Drools fraud-detection rule.

You are designing backend SQL for a new Drools rule.

Rule requirement:
Flag customers who made more than 5 transactions over $10,000 within 24 hours.

Think step by step about:
1. Which tables are needed
2. How transactions should be grouped
3. How time windows should be calculated
4. How the final dataset should be structured for Drools ingestion

----------
Then generate the SQL query.
----------

SELECT
    customer_id,
    COUNT(*) AS high_value_tx_count,
    MIN(transaction_time) AS first_tx,
    MAX(transaction_time) AS last_tx
FROM transactions
WHERE amount > 10000
GROUP BY customer_id, DATE(transaction_time)
HAVING COUNT(*) > 5;

----------

Why this is “Zero-shot CoT”
- Zero-shot → no examples were provided beforehand.
- Chain-of-Thought → the model is explicitly instructed to reason step-by-step before generating SQL.
- Useful when generating logic-heavy queries for rule engines like Drools.
```

- Context was limited to "Drools rule", "Fraud" and "SQL" 
    - It's precise, effective and easy to edit or correct. The product can become the context of the next prompts, and now it's an established known logic

## Advantages of chain of thought prompting
Users can benefit from several advantages within chain of thought prompting. Some of them include:

- **Improved prompt outputs:** CoT prompting improves LLMs' performance on complex reasoning tasks by breaking them down into simpler, logical steps.
- **Transparency and understanding:** The generation of intermediate reasoning steps offers transparency into how the model arrives at its conclusions, making the decision-making process more understandable for users.
- **Multistep reasoning:** By systematically tackling each component of a problem, CoT prompting often leads to more accurate and reliable answers, particularly in tasks requiring multistep reasoning. Multistep reasoning refers to the ability to perform complex logical operations by breaking them down into smaller, sequential steps. This cognitive skill is essential for solving intricate problems, making decisions and understanding cause-and-effect relationships. 
- **Attention to detail:** The step-by-step explanation model is akin to teaching methods that encourage understanding through detailed breakdowns, making CoT prompting useful in educational contexts.
- **Diversity:** CoT can be applied across a broad range of tasks, including but not limited to, arithmetic reasoning, common sense reasoning and complex problem-solving, demonstrating its flexible utility. 

### Downsides
- Expensive in tokens and computation power
- Quality of the prompt needs to be high and precise
- Misleading results if the prompt is not accurate, and hence leads to model-misunderstanding when working on the task
- Model overfitting; the ability to "think outside the box" can be reduced, and things will fall under this overfitted model
- Evaluation and validation: the evaluation and feedback is given to the complex response, not the baseline, and then the complexity of understanding has to be high by the human

(IBM https://www.ibm.com/think/topics/chain-of-thoughts)

