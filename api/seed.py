"""
Seed the database with rich mock articles and technical terms.
Run automatically on first startup if the database is empty.
"""

from sqlalchemy.orm import Session
from .models import Article, Term


MOCK_DATA = [
    {
        "title": "How Transformers Revolutionized Natural Language Processing",
        "source_url": "https://arxiv.org/abs/1706.03762",
        "source_type": "Article",
        "content": (
            "Before the Transformer architecture arrived in 2017, sequence modeling relied heavily on recurrent neural networks "
            "and their gated variants like LSTM and GRU. These models processed tokens one by one, making parallelization "
            "nearly impossible during training. The Transformer solved this bottleneck with a mechanism called self-attention, "
            "which allows every token in a sequence to directly attend to every other token simultaneously. "
            "Instead of recurrence, positional encoding is injected into the input embeddings to preserve word order. "
            "The model stacks multiple layers of multi-head attention and feed-forward networks, enabling it to capture "
            "both local syntax and long-range semantic dependencies with remarkable efficiency. "
            "This architecture became the backbone of models like BERT, GPT, and T5, fundamentally reshaping how machines understand language."
        ),
        "terms": [
            ("Transformer", "A neural network architecture introduced in the paper 'Attention Is All You Need' (2017). It relies entirely on attention mechanisms, discarding recurrence and convolution entirely. It became the foundation for nearly all modern large language models."),
            ("self-attention", "A mechanism that lets each position in a sequence look at all other positions to compute a new representation. It computes queries, keys, and values from the same input, measuring pairwise relevance between every token pair."),
            ("LSTM", "Long Short-Term Memory — a type of recurrent network designed to learn long-term dependencies. It uses three gates (input, forget, output) to control information flow, mitigating the vanishing gradient problem found in vanilla RNNs."),
            ("GRU", "Gated Recurrent Unit — a simpler RNN variant than LSTM with only two gates (reset and update). It achieves comparable performance on many tasks with fewer parameters."),
            ("positional encoding", "Since Transformers process all tokens simultaneously, positional encodings are added to embeddings to inject information about each token's position in the sequence. Commonly implemented as sine/cosine functions of different frequencies."),
            ("embeddings", "Dense, continuous vector representations of discrete tokens (words or subwords). Instead of one-hot vectors, embeddings capture semantic similarity — 'king' and 'queen' will be closer in embedding space than 'king' and 'table'."),
            ("BERT", "Bidirectional Encoder Representations from Transformers — a pre-trained model by Google that reads text in both directions. It's fine-tuned for tasks like classification, question answering, and named entity recognition."),
        ]
    },
    {
        "title": "Understanding Docker: Containers vs. Virtual Machines",
        "source_url": "https://www.docker.com/resources/what-container/",
        "source_type": "Article",
        "content": (
            "A container is a lightweight, portable unit that packages an application along with its dependencies, "
            "libraries, and configuration into a single runnable artifact. Unlike a virtual machine, a container does "
            "not include a full guest operating system. Instead, containers share the host kernel and isolate processes "
            "using Linux namespaces and control groups (cgroups). This makes containers dramatically faster to start "
            "and far more memory-efficient than VMs. Docker popularized containers by providing a simple CLI and a "
            "layered image format based on a union file system. Each instruction in a Dockerfile creates an immutable "
            "layer — unchanged layers are cached and reused, which accelerates builds significantly. "
            "Docker Compose extends this by letting you define multi-container applications in a single YAML manifest, "
            "orchestrating services like a web server, a database, and a cache together."
        ),
        "terms": [
            ("container", "A standard unit of software that packages code and all its dependencies. Containers are isolated from each other and the host, but share the OS kernel — making them much lighter than virtual machines."),
            ("virtual machine", "An emulation of an entire computer, including a guest OS, running on top of a hypervisor. VMs provide strong isolation but consume significantly more resources (RAM, disk, boot time) than containers."),
            ("Linux namespaces", "A kernel feature that partitions system resources (process IDs, network interfaces, mount points, users) so each container sees its own isolated view of the system. The foundation of container isolation."),
            ("cgroups", "Control Groups — a Linux kernel feature that limits, accounts for, and isolates the resource usage (CPU, memory, disk I/O) of groups of processes. Used by Docker to prevent any single container from monopolizing host resources."),
            ("Dockerfile", "A text file containing a sequence of instructions that Docker uses to build an image. Common instructions include FROM (base image), RUN (execute commands), COPY (add files), and CMD (default command to run)."),
            ("union file system", "A file system that layers multiple directories on top of each other, presenting them as a single merged view. Docker uses it so each image layer only stores the diff from the previous layer, saving significant disk space."),
            ("Docker Compose", "A tool for defining and running multi-container Docker applications. You write a docker-compose.yml file specifying services, networks, and volumes, then start everything with a single 'docker compose up' command."),
        ]
    },
    {
        "title": "The CAP Theorem: Why Distributed Systems Can't Have Everything",
        "source_url": "https://www.youtube.com/watch?v=BHqjEjzAicA",
        "source_type": "Video",
        "content": (
            "The CAP theorem, formulated by Eric Brewer in 2000, states that a distributed data store can only guarantee "
            "two of three properties simultaneously: Consistency, Availability, and Partition tolerance. "
            "Consistency means every read receives the most recent write or an error. "
            "Availability means every request receives a (non-error) response, though it might not contain the latest data. "
            "Partition tolerance means the system continues operating even if network partitions cause some nodes "
            "to be unable to communicate. In practice, network failures are inevitable, so partition tolerance is "
            "non-negotiable — forcing you to choose between consistency and availability during a partition. "
            "Systems like HBase and Zookeeper prioritize CP, while Cassandra and DynamoDB prioritize AP. "
            "Eventual consistency is a common AP trade-off: all nodes will converge to the same value, but not immediately."
        ),
        "terms": [
            ("CAP theorem", "A fundamental theorem in distributed computing proving that no distributed data store can simultaneously guarantee Consistency, Availability, and Partition tolerance. You must choose two, and since partitions happen, you're really choosing between C and A."),
            ("Consistency", "In the CAP theorem context: every node in a distributed system returns the most recent, agreed-upon value. After a write completes, all subsequent reads from any node will see that write. Not to be confused with the C in ACID."),
            ("Availability", "Every request to a non-failing node must receive a response. The system remains operational and responsive even if some nodes are down or partitioned — though the response may not reflect the absolute latest state."),
            ("Partition tolerance", "The system continues functioning correctly even when network partitions occur — i.e., when some nodes cannot communicate with others due to network failures. Real distributed systems must be partition-tolerant."),
            ("Cassandra", "An Apache distributed NoSQL database designed for high availability and linear scalability. It uses a peer-to-peer ring architecture with no single point of failure and prioritizes AP (availability + partition tolerance) in CAP terms."),
            ("Eventual consistency", "A consistency model guaranteeing that, if no new updates are made, all replicas will eventually converge to the same value. Used by AP systems like DynamoDB. Faster reads, but temporary staleness is possible."),
        ]
    },
    {
        "title": "How WebAssembly is Blurring the Line Between Native and Web",
        "source_url": "https://webassembly.org/getting-started/developers-guide/",
        "source_type": "Article",
        "content": (
            "WebAssembly (Wasm) is a binary instruction format designed as a portable compilation target for languages "
            "like C, C++, and Rust. Unlike JavaScript, which is parsed and JIT-compiled at runtime, Wasm is delivered "
            "as a pre-compiled binary, enabling near-native execution speeds inside the browser sandbox. "
            "The browser's JavaScript engine validates and compiles Wasm modules using ahead-of-time (AOT) compilation. "
            "Wasm runs in the same sandboxed environment as JS and cannot directly access the DOM — it communicates "
            "with JavaScript via a Foreign Function Interface (FFI). This makes it ideal for performance-critical tasks "
            "like video encoding, 3D rendering, cryptography, and physics simulations. "
            "Beyond the browser, the WASI (WebAssembly System Interface) standard is pushing Wasm into server-side "
            "and edge computing environments as a universal, secure, and portable runtime."
        ),
        "terms": [
            ("WebAssembly", "A low-level binary instruction format (bytecode) that runs in modern browsers at near-native speed. It's a compilation target for languages like C++, Rust, and Go — not a language you typically write by hand."),
            ("JIT-compiled", "Just-In-Time compilation. Code is compiled to machine code at runtime, right before execution, rather than ahead of time. JavaScript engines use JIT to optimize hot code paths, but it introduces startup latency."),
            ("sandboxed", "Executed in an isolated environment with no direct access to the host OS, file system, or network. Both WebAssembly and JavaScript run in the browser's sandbox, so a malicious module can't compromise your computer."),
            ("AOT compilation", "Ahead-Of-Time compilation. Code is fully compiled to machine code before execution begins (as opposed to JIT). Wasm uses AOT in the browser, which contributes to faster, more predictable startup times."),
            ("Foreign Function Interface", "A mechanism allowing code written in one language to call functions written in another. In the browser, Wasm uses FFI to call JavaScript functions and vice versa, enabling tight interop between the two runtimes."),
            ("WASI", "WebAssembly System Interface — a standard API allowing Wasm modules to interact with the operating system (files, network, clocks) in a capability-based, portable way. It enables running Wasm securely outside the browser."),
        ]
    },
    {
        "title": "Git Internals: What Actually Happens When You Commit",
        "source_url": "https://www.youtube.com/watch?v=lG90LZotrpo",
        "source_type": "Video",
        "content": (
            "At its core, Git is a content-addressable filesystem. Every object stored in Git — blobs, trees, and commits — "
            "is identified by a SHA-1 hash of its content. A blob stores raw file data. "
            "A tree object represents a directory listing, pointing to blobs (files) and other trees (subdirectories). "
            "A commit object points to a tree (the root snapshot), the parent commit(s), and metadata like author and message. "
            "When you run git commit, Git hashes all staged file contents into blob objects, builds a tree from the index, "
            "and wraps everything in a new commit object. A branch is simply a lightweight pointer to a commit hash — "
            "not a copy of files. Merging works by finding the common ancestor of two branches and applying the diverging "
            "changes. If Git can't auto-resolve a conflict, it marks the file with merge conflict markers for manual resolution."
        ),
        "terms": [
            ("content-addressable filesystem", "A storage system where data is stored and retrieved by its content hash (like SHA-1), not by its location or filename. If two files have identical content, they share one stored object. It ensures data integrity automatically."),
            ("SHA-1 hash", "A cryptographic hash function producing a 40-character hexadecimal string. Git uses SHA-1 to generate a unique ID for every object. Any change to the content produces a completely different hash, making data corruption detectable."),
            ("blob", "Binary Large OBject — Git's storage unit for raw file content. A blob contains only file data, no filename or permissions. The same content in two different files is stored as a single blob (deduplication by hash)."),
            ("tree object", "A Git object representing a directory. It contains a list of entries, each with a file mode, object type (blob or tree), SHA-1 hash, and filename. Trees map the directory structure of a snapshot."),
            ("commit object", "A Git object encapsulating a snapshot. It records the root tree hash, parent commit hash(es), author, committer, timestamp, and commit message. Commits form a directed acyclic graph (DAG) — the history."),
            ("merge conflict", "Occurs when two branches modify the same part of a file differently and Git cannot automatically determine which change to keep. Git inserts conflict markers (<<<<<<<, =======, >>>>>>>) and requires the developer to manually resolve."),
        ]
    },
]


def seed_database(db: Session):
    """Insert all mock articles and their associated terms into the database."""
    for entry in MOCK_DATA:
        article = Article(
            title=entry["title"],
            source_url=entry["source_url"],
            source_type=entry["source_type"],
            content=entry["content"],
        )
        db.add(article)
        db.flush()  # Get the article.id without committing

        for term_text, definition in entry["terms"]:
            term = Term(
                article_id=article.id,
                term=term_text,
                definition=definition,
            )
            db.add(term)

    db.commit()
    print(f"✅ Seeded {len(MOCK_DATA)} articles into the database.")